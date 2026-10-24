import { StrictMode, useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CloudShell from "./CloudShell";
import { api, downloadReport, openContractPdf } from "./api";

const auth = vi.hoisted(() => ({ session: null, listeners: new Set(), getSession: vi.fn() }));

vi.mock("./cloud", () => ({
  CLOUD_MODE: true,
  CLOUD_PROVIDER: "supabase",
  requestSession: async () => auth.session,
  supabase: { auth: {
    getSession: auth.getSession,
    onAuthStateChange: (callback) => {
      auth.listeners.add(callback);
      queueMicrotask(() => {
        if (auth.listeners.has(callback)) callback("INITIAL_SESSION", auth.session);
      });
      return { data: { listener: null, subscription: { unsubscribe: () => auth.listeners.delete(callback) } } };
    },
    signOut: async () => emit("SIGNED_OUT", null),
  } },
}));

vi.mock("./App", () => ({ default: function Workspace({ cloudUser, onSignOut }) {
  const [draft, setDraft] = useState("");
  const [section, setSection] = useState("Source files");
  const [caseName, setCase] = useState("Case A");
  const [busy, setBusy] = useState(false);
  return <div data-testid="workspace">
    <p>{cloudUser.email}</p>
    <label>Draft<input value={draft} onChange={(event) => setDraft(event.target.value)} /></label>
    <button onClick={() => setSection("Ask documents")}>{section}</button>
    <button onClick={() => setCase("Case B")}>{caseName}</button>
    <button onClick={() => setBusy(true)}>{busy ? "Review running" : "Start review"}</button>
    <button onClick={onSignOut}>Sign out</button>
  </div>;
} }));

function session(id = "user-1", email = "one@example.test", token = "token-1") {
  return { user: { id, email }, access_token: token };
}
function emit(event, next) {
  auth.session = next;
  for (const callback of auth.listeners) callback(event, next);
}
function response(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function mount() {
  return render(<StrictMode><CloudShell /></StrictMode>);
}
async function approved() {
  mount();
  await screen.findByTestId("workspace");
}

beforeEach(() => {
  auth.session = session();
  auth.listeners.clear();
  auth.getSession.mockReset();
  vi.stubGlobal("fetch", vi.fn(async () => response({ id: auth.session.user.id, email: auth.session.user.email, role: "reviewer" })));
});

describe("workspace access lifecycle", () => {
  it("shows sign-in without requesting /me when no session exists", async () => {
    auth.session = null;
    mount();
    await screen.findByLabelText("Invited email");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("blocks first entry, verifies once under Strict Mode, and verifies again on reload", async () => {
    const pending = deferred();
    fetch.mockReturnValueOnce(pending.promise);
    const view = mount();
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Checking your invitation");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await act(async () => pending.resolve(response({ ...auth.session.user, role: "reviewer" })));
    await screen.findByTestId("workspace");
    expect(auth.getSession).not.toHaveBeenCalled();
    view.unmount();
    mount();
    await screen.findByTestId("workspace");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("preserves the same workspace, draft, section, case and operation on focus and refresh", async () => {
    await approved();
    const workspace = screen.getByTestId("workspace");
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Unsaved question" } });
    fireEvent.click(screen.getByRole("button", { name: "Source files" }));
    fireEvent.click(screen.getByRole("button", { name: "Case A" }));
    fireEvent.click(screen.getByRole("button", { name: "Start review" }));
    await act(async () => {
      window.dispatchEvent(new Event("blur"));
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      emit("SIGNED_IN", session());
      emit("TOKEN_REFRESHED", session("user-1", " ONE@example.test ", "token-2"));
    });
    expect(screen.getByTestId("workspace")).toBe(workspace);
    expect(screen.getByLabelText("Draft")).toHaveValue("Unsaved question");
    for (const name of ["Ask documents", "Case B", "Review running"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(fetch).toHaveBeenCalledTimes(1);
    await api("/cases");
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe("Bearer token-2");
  });

  it.each([
    ["account", session("user-2", "two@example.test", "token-2")],
    ["email", session("user-1", "new@example.test", "token-2")],
  ])("clears private state and rechecks when the %s changes", async (_label, next) => {
    await approved();
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Private draft" } });
    const pending = deferred();
    fetch.mockReturnValueOnce(pending.promise);
    await act(async () => emit("USER_UPDATED", next));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    await act(async () => pending.resolve(response({ ...next.user, role: "reviewer" })));
    await screen.findByTestId("workspace");
    expect(screen.getByLabelText("Draft")).toHaveValue("");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("signs out immediately and ignores a late verification response", async () => {
    const pending = deferred();
    fetch.mockReturnValueOnce(pending.promise);
    mount();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await act(async () => emit("SIGNED_OUT", null));
    await act(async () => pending.resolve(response({ id: "user-1", email: "one@example.test" })));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Invited email")).toBeInTheDocument();
  });

  it("shows an initial invitation denial and can explicitly retry after being invited", async () => {
    fetch.mockResolvedValueOnce(response({ code: "invite_required", detail: "Invitation required" }, 403));
    mount();
    await screen.findByRole("alert");
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    await act(async () => emit("TOKEN_REFRESHED", session("user-1", "one@example.test", "token-2")));
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry verification" }));
    await screen.findByTestId("workspace");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("does not let an old account's response replace the new account", async () => {
    const old = deferred();
    fetch.mockReturnValueOnce(old.promise);
    mount();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await act(async () => emit("SIGNED_IN", session("user-2", "two@example.test", "token-2")));
    await screen.findByTestId("workspace");
    await act(async () => old.resolve(response({ id: "user-1", email: "one@example.test" })));
    expect(screen.getByText("two@example.test")).toBeInTheDocument();
    expect(screen.queryByText("one@example.test")).not.toBeInTheDocument();
  });

  it("keeps a failed entry check stable on focus, and retries exactly once on request", async () => {
    fetch.mockResolvedValueOnce(response({ code: "auth_unavailable", detail: "Please retry" }, 503));
    mount();
    await screen.findByRole("alert");
    await act(async () => emit("SIGNED_IN", session()));
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry verification" }));
    await screen.findByTestId("workspace");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("handles sign-out from an approved workspace", async () => {
    await approved();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
  });
});

describe("protected request failures", () => {
  it.each(["session_invalid", "account_unverified", "invite_required"])("removes access for %s", async (code) => {
    await approved();
    fetch.mockResolvedValueOnce(response({ code, detail: "Access denied" }, code === "session_invalid" ? 401 : 403));
    await act(async () => { await expect(api("/cases")).rejects.toThrow("Access denied"); });
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Access denied");
  });

  it.each([
    ["service outage", () => Promise.resolve(response({ code: "auth_unavailable", detail: "Retry later" }, 503))],
    ["resource permission", () => Promise.resolve(response({ detail: "Administrator access required" }, 403))],
    ["network outage", () => Promise.reject(new TypeError("Network failure"))],
  ])("preserves the workspace for a %s", async (_label, failure) => {
    await approved();
    const workspace = screen.getByTestId("workspace");
    fetch.mockImplementationOnce(failure);
    await act(async () => { await expect(api("/cases")).rejects.toThrow(); });
    expect(screen.getByTestId("workspace")).toBe(workspace);
  });

  it("ignores access failures from an old token", async () => {
    await approved();
    const old = deferred();
    fetch.mockReturnValueOnce(old.promise);
    const request = api("/cases");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await act(async () => emit("TOKEN_REFRESHED", session("user-1", "one@example.test", "new-token")));
    await act(async () => {
      old.resolve(response({ code: "session_invalid", detail: "Old token" }, 401));
      await expect(request).rejects.toThrow("Old token");
    });
    expect(screen.getByTestId("workspace")).toBeInTheDocument();
  });

  it("ignores access failures from the previous account", async () => {
    await approved();
    const old = deferred();
    fetch.mockReturnValueOnce(old.promise);
    const request = api("/cases");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await act(async () => emit("SIGNED_IN", session("user-2", "two@example.test", "token-2")));
    await screen.findByText("two@example.test");
    await act(async () => {
      old.resolve(response({ code: "invite_required", detail: "Previous account revoked" }, 403));
      await expect(request).rejects.toThrow("Previous account revoked");
    });
    expect(screen.getByText("two@example.test")).toBeInTheDocument();
  });

  it("retries initial verification with refreshed credentials when the old token fails", async () => {
    const old = deferred();
    fetch.mockReturnValueOnce(old.promise);
    mount();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await act(async () => emit("TOKEN_REFRESHED", session("user-1", "one@example.test", "new-token")));
    await act(async () => old.resolve(response({ code: "session_invalid", detail: "Old token" }, 401)));
    await screen.findByTestId("workspace");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["report download", () => downloadReport("case-1")],
    ["contract preview", () => openContractPdf("case-1", 1)],
  ])("applies the access gate to %s", async (_label, action) => {
    const close = vi.fn();
    vi.spyOn(window, "open").mockReturnValue({ close });
    await approved();
    fetch.mockResolvedValueOnce(response({ code: "invite_required", detail: "Invitation revoked" }, 403));
    await act(async () => { await expect(action()).rejects.toThrow("Invitation revoked"); });
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    if (_label === "contract preview") expect(close).toHaveBeenCalled();
  });
});
