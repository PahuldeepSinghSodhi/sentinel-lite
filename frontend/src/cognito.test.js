import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createCognitoClient } from "./cognito";

let client;
const jwt = (email = "one@example.test") => `header.${btoa(JSON.stringify({ sub:"cognito-user",email,email_verified:true,exp:Math.floor(Date.now()/1000)+900 }))}.signature`;
const tokens = (email) => ({ AccessToken:`access-${email || "one"}`,IdToken:jwt(email),RefreshToken:"synthetic-refresh" });
const response = (data,status=200) => ({ok:status<400,status,json:async()=>data});

beforeEach(() => {
  localStorage.clear();
  client=createCognitoClient({region:"ap-southeast-2",poolId:"test-pool",clientId:"test-client"});
});
afterEach(() => { client.dispose(); vi.unstubAllGlobals(); });

it("completes email-code sign-in and emits a stable account identity", async () => {
  const listener=vi.fn(); client.auth.onAuthStateChange(listener);
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({ChallengeName:"EMAIL_OTP",Session:"challenge"}))
    .mockResolvedValueOnce(response({AuthenticationResult:tokens()})));
  expect((await client.auth.signInWithOtp({email:" One@Example.test "})).error).toBeNull();
  expect((await client.auth.verifyOtp({token:"00112233"})).error).toBeNull();
  const session=(await client.auth.getSession()).data.session;
  expect(session.user).toEqual({id:"cognito-user",email:"one@example.test",email_confirmed_at:"verified"});
  expect(listener).toHaveBeenCalledWith("SIGNED_IN",session);
  expect(JSON.parse(fetch.mock.calls[0][1].body).AuthParameters.PREFERRED_CHALLENGE).toBe("EMAIL_OTP");
  expect(localStorage.getItem("sentinel-cognito-test-pool-test-client")).not.toContain("invited");
});

it("removes the session immediately during a delayed remote sign-out", async () => {
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({ChallengeName:"EMAIL_OTP",Session:"challenge"}))
    .mockResolvedValueOnce(response({AuthenticationResult:tokens()})));
  await client.auth.signInWithOtp({email:"one@example.test"}); await client.auth.verifyOtp({token:"00112233"});
  let finish; fetch.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  const leaving=client.auth.signOut();
  expect((await client.auth.getSession()).data.session).toBeNull();
  expect(localStorage.getItem("sentinel-cognito-test-pool-test-client")).toBeNull();
  finish(response({})); await leaving;
});

it("reports a retryable outage without inventing a signed-in account", async () => {
  vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new TypeError("network")));
  const result=await client.auth.signInWithOtp({email:"one@example.test"});
  expect(result.error.code).toBe("auth_unavailable");
  expect((await client.auth.getSession()).data.session).toBeNull();
});

it("uses cross-tab sign-out to remove private authentication state", async () => {
  const listener=vi.fn(); client.auth.onAuthStateChange(listener);
  window.dispatchEvent(new StorageEvent("storage",{key:"sentinel-cognito-test-pool-test-client",newValue:null}));
  expect(listener).toHaveBeenCalledWith("SIGNED_OUT",null);
  expect((await client.auth.getSession()).data.session).toBeNull();
});

it("does not restore an account when code verification finishes after sign-out", async () => {
  let finish;
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({ChallengeName:"EMAIL_OTP",Session:"challenge",ChallengeParameters:{USERNAME:"canonical-subject"}}))
    .mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})));
  await client.auth.signInWithOtp({email:"one@example.test"});
  const verification=client.auth.verifyOtp({token:"00112233"});
  expect(JSON.parse(fetch.mock.calls[1][1].body).ChallengeResponses.USERNAME).toBe("canonical-subject");
  await client.auth.signOut();
  finish(response({AuthenticationResult:tokens()}));
  expect((await verification).error.message).toContain("cancelled");
  expect((await client.auth.getSession()).data.session).toBeNull();
});

it("lets an account selected in another tab win over a delayed code response",async()=>{
  let finish;
  vi.stubGlobal("fetch",vi.fn().mockResolvedValueOnce(response({ChallengeName:"EMAIL_OTP",Session:"challenge"}))
    .mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})));
  await client.auth.signInWithOtp({email:"one@example.test"});
  const verification=client.auth.verifyOtp({token:"00112233"});
  const other={access_token:"access-two",identity_token:jwt("two@example.test"),refresh_token:"refresh-two",
    expires_at:Math.floor(Date.now()/1000)+900,user:{id:"second-account",email:"two@example.test"}};
  window.dispatchEvent(new StorageEvent("storage",{key:"sentinel-cognito-test-pool-test-client",newValue:JSON.stringify(other)}));
  finish(response({AuthenticationResult:tokens()}));
  expect((await verification).error.message).toContain("cancelled");
  expect((await client.auth.getSession()).data.session.user.id).toBe("second-account");
});
