// Installed Chrome, real AWS reads/authentication, isolated disposable browser profile.
// Credentials arrive only through stdin and are never logged or retained.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { chromium } from "playwright";

let input=""; for await (const part of process.stdin) input+=part;
const config=JSON.parse(input);input="";
const identity=token=>JSON.parse(Buffer.from(token.split(".")[1],"base64url").toString());
function session(tokens,oldRefresh) {
  const user=identity(tokens.IdToken);
  return {access_token:tokens.AccessToken,identity_token:tokens.IdToken,refresh_token:tokens.RefreshToken||oldRefresh,
    expires_at:user.exp,user:{id:user.sub,email:user.email,email_confirmed_at:"verified"}};
}
const storageKey=`sentinel-cognito-${config.pool}-${config.client}`;
const profile=await mkdtemp(join(tmpdir(),"sentinel-aws-smoke-"));
let chrome,browser;
try {
  chrome=spawn("C:/Program Files/Google/Chrome/Application/chrome.exe",["--headless=new","--remote-debugging-port=0",`--user-data-dir=${profile}`,"--no-first-run","--no-default-browser-check","about:blank"],{windowsHide:true,stdio:"ignore"});
  await new Promise((yes,no)=>{chrome.once("spawn",yes);chrome.once("error",no);});
  let port;
  for(let i=0;i<100&&!port;i++){
    try{port=(await readFile(join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0];}
    catch{await new Promise(done=>setTimeout(done,100));}
  }
  assert.ok(port);
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`,{noDefaults:true});
  const context=browser.contexts()[0];
  await context.addInitScript(({key,value})=>{
    if(!localStorage.getItem(key))localStorage.setItem(key,JSON.stringify(value));
  },{key:storageKey,value:session(config.tokens)});
  const page=await context.newPage();page.setDefaultTimeout(30000);
  const requests=[],errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("request",r=>{if(r.url().startsWith(config.api))requests.push({path:new URL(r.url()).pathname,method:r.method()});});
  await page.goto(config.url);
  const chooser=page.getByRole("combobox",{name:"Select review case"});
  await chooser.waitFor();
  await page.waitForFunction(()=>!document.querySelector(".case-switcher select")?.disabled);
  assert.equal(await page.getByText("Couldn’t load workspace",{exact:true}).count(),0);
  await chooser.selectOption(config.smallCase);
  await page.waitForFunction(()=>!document.querySelector(".case-switcher select")?.disabled);
  await page.getByRole("button",{name:"Ask documents",exact:true}).first().click();
  const draft=page.getByRole("textbox",{name:"Your document question"});
  await draft.fill("Keep this unsent AWS smoke-test draft");
  const meCount=()=>requests.filter(r=>r.path==="/me").length;
  assert.equal(meCount(),1);
  const other=await context.newPage();await other.goto(config.url);
  const first=await context.newCDPSession(page),second=await context.newCDPSession(other);
  assert.equal((await first.send("Browser.getWindowForTarget")).windowId,(await second.send("Browser.getWindowForTarget")).windowId);
  for(let i=0;i<3;i++){
    await other.bringToFront();await page.waitForFunction(()=>document.visibilityState==="hidden");
    await page.bringToFront();await page.waitForFunction(()=>document.visibilityState==="visible");
    assert.equal(await draft.inputValue(),"Keep this unsent AWS smoke-test draft");
    assert.equal(await chooser.inputValue(),config.smallCase);
  }
  // Refresh native Cognito credentials, then exercise the real cross-tab event.
  const refreshed=await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`,{method:"POST",
    headers:{"Content-Type":"application/x-amz-json-1.1","X-Amz-Target":"AWSCognitoIdentityProviderService.InitiateAuth"},
    body:JSON.stringify({ClientId:config.client,AuthFlow:"REFRESH_TOKEN_AUTH",AuthParameters:{REFRESH_TOKEN:config.tokens.RefreshToken}})});
  assert.ok(refreshed.ok);
  const tokens=(await refreshed.json()).AuthenticationResult;
  await other.evaluate(({key,value})=>localStorage.setItem(key,JSON.stringify(value)),{key:storageKey,value:session(tokens,config.tokens.RefreshToken)});
  await page.bringToFront();
  assert.equal(await draft.inputValue(),"Keep this unsent AWS smoke-test draft");
  assert.equal(await chooser.inputValue(),config.smallCase);
  assert.equal(meCount(),1);
  // Every new page load still requires one real invitation check.
  await page.reload();
  await page.waitForFunction(()=>!document.querySelector(".case-switcher select")?.disabled);
  await chooser.waitFor();
  assert.equal(meCount(),2);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({browser:"Google Chrome",services:"real AWS",tabReturns:3,
    sameWindow:true,caseAndDraftPreserved:true,nativeRefreshPreservedWorkspace:true,
    invitationChecksBeforeReload:1,invitationChecksAfterReload:2,consoleErrors:errors,
    requestPaths:requests},null,2));
} finally {
  await browser?.close();
  if(chrome&&chrome.exitCode===null){const exit=new Promise(done=>chrome.once("exit",done));chrome.kill();await exit;}
  assert.equal(dirname(resolve(profile)),resolve(tmpdir()));
  assert.ok(basename(profile).startsWith("sentinel-aws-smoke-"));
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});
}
