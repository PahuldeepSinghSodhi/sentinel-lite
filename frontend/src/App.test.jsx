import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { api } from "./api";

vi.mock("./cloud", () => ({ CLOUD_MODE: true, requestSession: async () => ({ access_token: "synthetic" }) }));
vi.mock("./CloudSettings", () => ({ default: () => <p>Settings content</p> }));
vi.mock("./components/DocumentsTab", () => ({ default: ({ review }) => <p>{review ? `Files for ${review.name}` : "Create a review case"}</p> }));
vi.mock("./components/AnomalyTab", () => ({ default: () => <p>Anomaly content</p> }));
vi.mock("./components/QueryTab", () => ({ default: () => <label>Draft question<input /></label> }));

const review = (id = "case-a") => ({ id, name: id === "case-a" ? "Case A" : "Case B", ready: true, status: "active", created_at: "2026-10-20", scans: [], questions: [] });
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function mount() { render(<StrictMode><App cloudUser={{ id: "test-user", role: "reviewer" }} /></StrictMode>); }

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    const path = new URL(url).pathname;
    if (path === "/cases") return response([review(), review("case-b")]);
    if (path.startsWith("/cases/")) return response(review(path.split("/")[2]));
    return response({});
  }));
});

it("keeps placeholders until the selected case loads, without showing an empty workspace", async () => {
  const pending = deferred();
  const fallback = fetch.getMockImplementation();
  fetch.mockImplementation((url) => new URL(url).pathname === "/cases/case-a" ? pending.promise : fallback(url));
  mount();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/cases/case-a"), expect.anything()));
  expect(screen.getByText("Loading your workspace…")).toBeVisible();
  expect(screen.getByLabelText("Loading case content")).toBeVisible();
  expect(screen.queryByText("No review case yet")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /New case/ })).toBeDisabled();
  const status = screen.getByText("Loading your workspace…");
  const settings = screen.getByRole("button", { name: "Settings", exact: true });
  expect(status.closest(".topbar-actions")).toContainElement(settings);
  await act(async () => pending.resolve(response(review())));
  await waitFor(() => expect(screen.getByText("Files for Case A")).toBeVisible());
  expect(screen.queryByLabelText("Loading case content")).not.toBeInTheDocument();
  expect(screen.queryByText("Loading your workspace…")).not.toBeInTheDocument();
});

it("shows an error with Retry, then loads without a page reload", async () => {
  const fallback = fetch.getMockImplementation();
  let failed = true;
  fetch.mockImplementation((url) => new URL(url).pathname === "/cases" && failed
    ? response({ detail: "Case service unavailable" }, 503) : fallback(url));
  mount();
  await screen.findByText("Couldn’t load workspace");
  expect(screen.queryByText("No review case yet")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /New case/ })).toBeDisabled();
  failed = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry", exact: true }));
  await waitFor(() => expect(screen.getByText("Files for Case A")).toBeVisible());
  expect(screen.queryByText("Couldn’t load workspace")).not.toBeInTheDocument();
});

it("shows a real empty state only after a successful empty response", async () => {
  const fallback = fetch.getMockImplementation();
  fetch.mockImplementation((url) => new URL(url).pathname === "/cases" ? response([]) : fallback(url));
  mount();
  await screen.findByText("No review case yet");
  expect(screen.getByText("Create a review case")).toBeVisible();
  expect(screen.getByRole("button", { name: /New case/ })).toBeEnabled();
});

it("shows case placeholders during switching and retries a failed selection", async () => {
  mount();
  await waitFor(() => expect(screen.getByText("Files for Case A")).toBeVisible());
  const pending = deferred();
  fetch.mockReturnValueOnce(pending.promise);
  fireEvent.change(screen.getByRole("combobox", { name: "Select review case" }), { target: { value: "case-b" } });
  expect(screen.getByText("Loading case…")).toBeVisible();
  expect(screen.getByText("Files for Case A")).not.toBeVisible();
  await act(async () => pending.resolve(response({ detail: "Try again" }, 503)));
  expect(screen.getByText("Couldn’t load case")).toBeVisible();
  expect(screen.getByText("Files for Case A")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry", exact: true }));
  await waitFor(() => expect(screen.getByText("Files for Case B")).toBeVisible());
});

it("keeps the status until concurrent requests finish and preserves drafts", async () => {
  mount();
  await waitFor(() => expect(screen.getByText("Files for Case A")).toBeVisible());
  fireEvent.click(screen.getAllByRole("button", { name: "Ask documents", exact: true })[0]);
  fireEvent.change(screen.getByLabelText("Draft question"), { target: { value: "Keep this question" } });
  const first = deferred(), second = deferred();
  fetch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  let firstRequest, secondRequest;
  act(() => { firstRequest = api("/me/model"); secondRequest = api("/me/storage"); });
  expect(screen.getByText("Updating workspace…")).toBeVisible();
  await act(async () => { first.resolve(response({})); await firstRequest; });
  expect(screen.getByText("Updating workspace…")).toBeVisible();
  await act(async () => { second.resolve(response({})); await secondRequest; });
  expect(screen.queryByText("Updating workspace…")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Draft question")).toHaveValue("Keep this question");
  const quiet = deferred();
  fetch.mockReturnValueOnce(quiet.promise);
  let quietRequest;
  act(() => { quietRequest = api("/cases/case-a", { silent: true }); });
  expect(screen.queryByText("Updating workspace…")).not.toBeInTheDocument();
  await act(async () => { quiet.resolve(response(review())); await quietRequest; });
});
