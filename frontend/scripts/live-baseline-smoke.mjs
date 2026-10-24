// Read-only production check. Receives a short-lived session on stdin; never saves it.
import assert from "node:assert/strict";
import { chromium } from "playwright";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
});
const result = { services: "deployed", passed: false, invitationChecks: 0,
  tabReturns: 0, failedResponses: [], browserErrors: 0, blockedWrites: 0 };
try {
  const context = await browser.newContext();
  await context.addInitScript(({ session, project, caseId, origin }) => {
    if (location.origin !== origin) return;
    if (!localStorage.getItem(`sb-${project}-auth-token`)) {
      localStorage.setItem(`sb-${project}-auth-token`, JSON.stringify(session));
      localStorage.setItem(`sentinel-active-case-${session.user.id}`, caseId);
    }
  }, config);
  const page = await context.newPage();
  page.on("pageerror", () => { result.browserErrors += 1; });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin !== config.api) return;
    if (url.pathname === "/me") result.invitationChecks += 1;
    if (response.status() >= 400) result.failedResponses.push(response.status());
  });
  await context.route(`${config.api}/**`, (route) => {
    if (!["GET", "OPTIONS"].includes(route.request().method()) || new URL(route.request().url()).pathname.endsWith("/report")) {
      result.blockedWrites += 1;
      return route.abort();
    }
    return route.continue();
  });
  const start = performance.now();
  await page.goto(config.origin, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "New case", exact: true }).waitFor({ state: "visible", timeout: 60000 });
  await page.waitForFunction(() => !document.querySelector(".case-switcher")?.matches('[aria-busy="true"]'), null, { timeout: 60000 });
  assert.equal(await page.getByRole("combobox").inputValue(), config.caseId);
  result.workspaceReadyMs = Math.round(performance.now() - start);
  await page.getByRole("button", { name: "Anomaly review", exact: true }).click();
  await page.getByRole("button", { name: "Ask documents", exact: true }).click();
  const draft = page.getByRole("textbox").first();
  await draft.fill("Unsent synthetic baseline draft");
  const other = await context.newPage();
  await other.goto("about:blank");
  for (let i = 0; i < 3; i += 1) {
    await other.bringToFront();
    await page.bringToFront();
    assert.equal(await draft.inputValue(), "Unsent synthetic baseline draft");
    result.tabReturns += 1;
  }
  assert.equal(result.invitationChecks, 1);
  assert.equal(result.blockedWrites, 0);
  assert.equal(result.browserErrors, 0);
  assert.deepEqual(result.failedResponses, []);
  result.passed = true;
} catch (error) {
  // Do not expose private DOM text, URLs, or tokens in assertion errors.
  result.failureType = error.name;
  process.exitCode = 1;
} finally {
  await browser.close();
  console.log(JSON.stringify(result));
}
