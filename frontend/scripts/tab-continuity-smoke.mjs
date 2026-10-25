// Exercises the real React app and Supabase client in installed Chrome, with synthetic services.
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { chromium } from "playwright";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const root = fileURLToPath(new URL("..", import.meta.url));
Object.assign(process.env, {
  VITE_SENTINEL_MODE: "cloud",
  VITE_API_BASE_URL: "https://api.sentinel.test",
  VITE_SUPABASE_URL: "https://sentinel-smoke.supabase.co",
  VITE_SUPABASE_ANON_KEY: "synthetic-public-key",
});
const server = await createServer({
  root, configFile: false, plugins: [react()],
  server: { host: "127.0.0.1", port: 5178, strictPort: true },
});
let browser;
let chrome;
const profile = await mkdtemp(join(tmpdir(), "sentinel-chrome-smoke-"));
try {
  await server.listen();
  chrome = spawn(process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe", [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--no-default-browser-check", "about:blank",
  ], { windowsHide: true, stdio: "ignore" });
  const chromeStarted = new Promise((resolve, reject) => {
    chrome.once("spawn", resolve);
    chrome.once("error", reject);
  });
  await chromeStarted;
  let port;
  for (let attempt = 0; attempt < 100 && !port; attempt += 1) {
    try { port = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]; }
    catch { await new Promise((resolve) => setTimeout(resolve, 100)); }
  }
  assert.ok(port, "Chrome must expose its test debugging endpoint");
  // Attach without Playwright's focus override so real background tabs become hidden.
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { noDefaults: true });
  const context = browser.contexts()[0];
  const account = { id: "00000000-0000-4000-8000-000000000001", email: "smoke@example.test", email_confirmed_at: "2026-10-20T00:00:00Z" };
  const token = (suffix) => [
    Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
    Buffer.from(JSON.stringify({ sub: account.id, email: account.email, exp: Math.floor(Date.now() / 1000) + 3600, suffix })).toString("base64url"),
    "synthetic-signature",
  ].join(".");
  const session = { access_token: token("first"), refresh_token: "synthetic-refresh", token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: account };
  await context.addInitScript((value) => {
    if (!localStorage.getItem("sb-sentinel-smoke-auth-token")) {
      localStorage.setItem("sb-sentinel-smoke-auth-token", JSON.stringify(value));
    }
  }, session);
  const review = (id) => ({
    id, name: id === "case-a" ? "Synthetic case A" : "Synthetic case B",
    created_at: "2026-10-20T00:00:00Z", status: "active", ready: true,
    files: {}, scans: [], questions: [], can_report: false,
  });
  let revoked = false;
  let outage = false;
  let completeQuestion;
  let releaseCases;
  const casesPending = new Promise((resolve) => { releaseCases = resolve; });
  const questionPending = new Promise((resolve) => { completeQuestion = resolve; });
  const requests = [];
  await context.route("https://api.sentinel.test/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const headers = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers });
    requests.push({ path, method });
    if (revoked) return route.fulfill({ status: 403, headers, json: { code: "invite_required", detail: "Invitation revoked" } });
    if (outage) return route.fulfill({ status: 503, headers, json: { code: "auth_unavailable", detail: "Service unavailable; please retry" } });
    let body;
    if (path === "/me") body = { ...account, role: "reviewer" };
    else if (path === "/") body = { status: "ready", mode: "cloud" };
    else if (path === "/cases") { await casesPending; body = [review("case-a"), review("case-b")]; }
    else if (path === "/me/model") body = { configured: false, choices: { ollama_cloud: ["gpt-oss:20b"] } };
    else if (path === "/me/storage") body = {};
    else if (path.endsWith("/questions")) { await questionPending; body = {}; }
    else if (path === "/cases/case-a" || path === "/cases/case-b") body = review(path.split("/")[2]);
    else throw new Error(`Unexpected API route: ${method} ${path}`);
    await route.fulfill({ headers, json: body });
  });
  await context.route("https://sentinel-smoke.supabase.co/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/token")) return route.fulfill({ json: { ...session, access_token: token("refreshed") } });
    if (path.endsWith("/user")) return route.fulfill({ json: account });
    if (path.endsWith("/logout")) return route.fulfill({ status: 204 });
    throw new Error(`Unexpected authentication route: ${path}`);
  });
  const page = await context.newPage();
  await page.setViewportSize({ width: 1440, height: 1000 });
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:5178");
  await page.getByText("Loading your workspace…", { exact: true }).waitFor();
  assert.equal(await page.getByText("No review case yet", { exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "New case", exact: true }).isDisabled(), true);
  const statusBox = await page.locator(".workspace-load-status").boundingBox();
  const settingsBox = await page.getByRole("button", { name: "Settings", exact: true }).boundingBox();
  assert.ok(statusBox.x + statusBox.width <= settingsBox.x, "Loading status belongs immediately left of Settings");
  const screenshots = join(root, "test-artifacts");
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({ path: join(screenshots, "workspace-loading-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: join(screenshots, "workspace-loading-mobile.png") });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, "Mobile layout must not overflow");
  await page.setViewportSize({ width: 1440, height: 1000 });
  releaseCases();
  await page.getByRole("button", { name: "New case", exact: true }).waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector(".case-switcher select")?.disabled);
  await page.getByRole("combobox", { name: "Select review case" }).selectOption("case-b");
  await page.getByRole("button", { name: "Ask documents", exact: true }).first().click();
  const question = page.getByRole("textbox", { name: "Your document question" });
  await question.fill("Keep this unsent question");
  const [other] = await Promise.all([
    page.waitForEvent("popup"),
    page.evaluate(() => { window.open("about:blank", "_blank"); }),
  ]);
  const firstTab = await context.newCDPSession(page);
  const secondTab = await context.newCDPSession(other);
  assert.equal((await firstTab.send("Browser.getWindowForTarget")).windowId,
    (await secondTab.send("Browser.getWindowForTarget")).windowId, "Smoke test requires two tabs in one window");
  const meCount = () => requests.filter((item) => item.path === "/me").length;
  assert.equal(meCount(), 1);
  const totalBefore = requests.length;
  for (let i = 0; i < 3; i += 1) {
    await other.bringToFront();
    await page.waitForFunction(() => document.visibilityState === "hidden", null, { polling: 100 });
    await page.bringToFront();
    await page.waitForFunction(() => document.visibilityState === "visible", null, { polling: 100 });
    assert.equal(await question.inputValue(), "Keep this unsent question");
    assert.equal(await page.getByRole("combobox", { name: "Select review case" }).inputValue(), "case-b");
    assert.equal(await page.getByText("Checking your invitation…").count(), 0);
  }
  // Refresh through the real client, including its TOKEN_REFRESHED event.
  await page.evaluate(async () => {
    const { supabase } = await import("/src/cloud.js");
    const result = await supabase.auth.refreshSession();
    if (result.error) throw result.error;
  });
  assert.equal(await question.inputValue(), "Keep this unsent question");
  await page.locator(".workspace-load-status").filter({ hasText: "Updating workspace…" }).waitFor({ state: "hidden" });
  assert.equal(meCount(), 1);
  assert.equal(requests.length, totalBefore);

  // An in-flight operation must also survive a genuine tab visibility transition.
  await page.getByRole("button", { name: "Ask Sentinel", exact: true }).click();
  await page.getByRole("button", { name: "Finding an answer…" }).waitFor();
  await page.getByText("Updating workspace…", { exact: true }).waitFor();
  await other.bringToFront();
  await page.waitForFunction(() => document.visibilityState === "hidden", null, { polling: 100 });
  await page.bringToFront();
  await page.waitForFunction(() => document.visibilityState === "visible", null, { polling: 100 });
  assert.equal(await question.isDisabled(), true);
  assert.equal(meCount(), 1);
  completeQuestion();
  await page.getByRole("button", { name: "Ask Sentinel", exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector("#question").disabled);

  outage = true;
  await question.fill("Temporary outage preserves this text");
  await page.getByRole("button", { name: "Ask Sentinel", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Service unavailable" }).waitFor();
  assert.equal(await question.inputValue(), "Temporary outage preserves this text");
  outage = false;
  revoked = true;
  await page.getByRole("button", { name: "Ask Sentinel", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Invitation revoked" }).waitFor();
  assert.equal(await page.locator(".workspace").count(), 0);
  await page.getByRole("button", { name: "Sign out and try another account" }).click();
  await page.getByRole("textbox", { name: "Invited email" }).waitFor();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ browser: "Google Chrome", services: "synthetic", tabReturns: 4, invitationChecksBeforeRevocation: meCount(), statePreserved: true, pendingOperationPreserved: true, outagePreservedWorkspace: true, revocationBlockedAccess: true, consoleErrors: errors }, null, 2));
} finally {
  await browser?.close();
  if (chrome && chrome.exitCode === null) {
    const exited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill();
    await exited;
  }
  assert.equal(dirname(resolve(profile)), resolve(tmpdir()));
  assert.ok(basename(profile).startsWith("sentinel-chrome-smoke-"));
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  await server.close();
}
