// Real installed Chrome, real AWS, disposable profile; credentials only via stdin.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {chromium} from "playwright";

let input="";for await(const part of process.stdin)input+=part;
const config=JSON.parse(input);input="";
const claims=JSON.parse(Buffer.from(config.tokens.IdToken.split(".")[1],"base64url").toString());
const profile=await mkdtemp(join(tmpdir(),"sentinel-sample-fix-"));
let chrome,browser,page;
const responses=[];
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
  await context.addInitScript(()=>{
    const original=URL.createObjectURL;
    window.__sentinelSmokeBlobSizes=[];
    URL.createObjectURL=function(blob){window.__sentinelSmokeBlobSizes.push(blob.size);return original.call(URL,blob);};
  });
  await context.addInitScript(({key,value})=>{
    if(!localStorage.getItem(key))localStorage.setItem(key,JSON.stringify(value));
  },{key:`sentinel-cognito-${config.pool}-${config.client}`,value:{
    access_token:config.tokens.AccessToken,identity_token:config.tokens.IdToken,refresh_token:config.tokens.RefreshToken,
    expires_at:claims.exp,user:{id:claims.sub,email:claims.email,email_confirmed_at:"verified"}}});
  page=await context.newPage();page.setDefaultTimeout(30000);await page.setViewportSize({width:1440,height:1000});
  page.on("response",r=>{const u=new URL(r.url());if(u.hostname.endsWith("amazonaws.com"))responses.push({host:u.hostname,status:r.status(),report:u.pathname.endsWith("/report")});});
  const errors=[],requests=[];
  page.on("pageerror",e=>errors.push(e.message));
  page.on("request",r=>{if(r.url().startsWith(config.api))requests.push({path:new URL(r.url()).pathname,method:r.method()});});
  await page.goto(config.url);
  const chooser=page.getByRole("combobox",{name:"Select review case"});
  const sample=page.getByRole("button",{name:"Try sample",exact:false});
  await sample.waitFor();
  await page.waitForFunction(()=>!document.querySelector(".case-switcher select")?.disabled);
  await sample.click();
  await page.waitForFunction(()=>!document.querySelector(".case-switcher select")?.disabled);
  if(config.fresh)config.sampleCase=await chooser.inputValue();
  assert.equal(await chooser.inputValue(),config.sampleCase);
  for(const name of ["sample_transactions.csv","rate_card.csv","service_agreement.txt"])
    await page.getByText(name,{exact:true}).waitFor();
  await page.locator('.upload-footer strong').getByText('Review active',{exact:true}).waitFor();
  await sample.click();
  await page.waitForFunction(()=>!document.querySelector(".case-switcher select")?.disabled);
  assert.equal(await chooser.inputValue(),config.sampleCase);
  await page.getByRole("button",{name:"Anomaly review",exact:true}).first().click();
  if(config.fresh)await page.getByRole('button',{name:'Run scan',exact:true}).click();
  await page.getByRole("button",{name:"Transactions reviewed: 12. View source files"}).waitFor();
  const source=page.locator(".evidence-link").first();await source.click();
  await page.locator(".evidence-preview").first().waitFor();
  const reportResponse=page.waitForResponse(r=>new URL(r.url()).hostname.includes(".s3.")&&r.request().method()==="GET");
  await page.getByRole("button",{name:"Download report",exact:true}).click();
  const downloaded=await reportResponse;assert.equal(downloaded.status(),200);
  await page.waitForFunction(()=>!document.querySelector('.report-bar button')?.disabled);
  assert.equal(await page.locator('.notice.error').count(),0);
  const sizes=await page.evaluate(()=>window.__sentinelSmokeBlobSizes);
  assert.ok(sizes.some(size=>size>1000),"Chrome must receive a nonempty report Blob");
  if(config.fresh){
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({browser:'Google Chrome',testedUrl:config.url,freshInvitedAccount:true,threeFilesVisible:true,
      sampleScanRows:12,privateReportDownloaded:true,noAiKeyRequired:true,consoleErrors:errors,requests}));
  } else {
  await page.getByRole("button",{name:"Source files",exact:true}).first().click();
  await chooser.selectOption(config.customCase);
  const upload=page.getByLabel("Upload transactions");await upload.waitFor();
  await upload.setInputFiles({name:"random.csv",mimeType:"text/csv",buffer:Buffer.from("random_column,other_column\none,two\n")});
  await page.getByText(/Missing required columns/).first().waitFor();
  await page.waitForFunction(()=>!document.querySelector('input[aria-label="Upload transactions"]')?.disabled);
  if(config.screenshotPath)await page.screenshot({path:config.screenshotPath,fullPage:true});
  await upload.setInputFiles({name:"sample_transactions.csv",mimeType:"text/csv",buffer:Buffer.from(config.csv)});
  await page.getByText("sample_transactions.csv",{exact:true}).waitFor();
  await page.waitForFunction(()=>!document.querySelector('input[aria-label="Upload transactions"]')?.disabled);
  await page.reload();await upload.waitFor();
  await page.getByText("sample_transactions.csv",{exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({browser:"Google Chrome",testedUrl:config.url,sampleReused:true,threeFilesVisible:true,
    sampleScanRows:12,evidenceOpened:true,privateReportDownloaded:true,invalidCsvReasonVisible:true,
    validRetrySucceeded:true,reloadPreservedFile:true,consoleErrors:errors,requests},null,2));
  }
} catch(error) {
  if(page)console.error(JSON.stringify({notices:await page.locator(".notice.error").allTextContents(),responses:responses.slice(-8)}));
  throw error;
} finally {
  await browser?.close();chrome?.kill();
  await rm(profile,{recursive:true,force:true,maxRetries:5,retryDelay:200});
}
