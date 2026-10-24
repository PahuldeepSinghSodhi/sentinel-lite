// Cognito email-code adapter with the same session-event contract as the existing provider.
// Only authentication tokens persist. Invitation approval remains in CloudShell memory.
export function createCognitoClient({ region, poolId, clientId }) {
  if (!region || !poolId || !clientId) throw new Error("AWS authentication is not configured");
  const endpoint = `https://cognito-idp.${region}.amazonaws.com/`;
  const storageKey = `sentinel-cognito-${poolId}-${clientId}`;
  const listeners = new Set();
  let session = null;
  let pending = null;
  let refreshing = null;
  let timer;
  let loginGeneration = 0;
  try { session = JSON.parse(localStorage.getItem(storageKey) || "null"); } catch { /* corrupted session */ }

  function decode(token) {
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0))));
  }
  async function call(operation, body) {
    let response;
    try {
      response = await fetch(endpoint, { method: "POST", signal: AbortSignal.timeout(15000),
        headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${operation}` }, body: JSON.stringify(body) });
    } catch {
      const error = new Error("Login service is unavailable. Please retry.");
      error.code = "auth_unavailable";
      throw error;
    }
    const data = await response.json();
    if (!response.ok) {
      const code = (data.__type || "").split("#").at(-1);
      const error = new Error(code === "CodeMismatchException" ? "That code did not match. Please try again."
        : code === "ExpiredCodeException" ? "That code expired. Request a new code."
        : "Could not sign in. Check your invitation and try again.");
      error.providerCode = code;
      error.code = response.status >= 500 || code === "TooManyRequestsException" ? "auth_unavailable" : "session_invalid";
      throw error;
    }
    return data;
  }
  function publish(event, value, persist = true) {
    session = value;
    if (persist) {
      if (value) localStorage.setItem(storageKey, JSON.stringify(value));
      else localStorage.removeItem(storageKey);
    }
    clearTimeout(timer);
    if (value) timer = setTimeout(() => { refresh().catch(() => {
      if (session) timer = setTimeout(() => refresh().catch(() => {}), 30000);
    }); }, Math.max(1000, (value.expires_at * 1000) - Date.now() - 60000));
    for (const listener of listeners) listener(event, value);
  }
  function fromTokens(tokens, oldRefresh) {
    const identity = decode(tokens.IdToken);
    return { access_token: tokens.AccessToken, identity_token: tokens.IdToken,
      refresh_token: tokens.RefreshToken || oldRefresh, expires_at: identity.exp,
      user: { id: identity.sub, email: identity.email, email_confirmed_at: identity.email_verified ? "verified" : null } };
  }
  async function refresh() {
    if (!session) return null;
    if (refreshing) return refreshing;
    const origin = session;
    refreshing = (async () => {
      try {
        const result = await call("InitiateAuth", { ClientId: clientId, AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: origin.refresh_token } });
        if (session !== origin) return session; // sign-out/account change wins over a delayed refresh
        const next = fromTokens(result.AuthenticationResult, origin.refresh_token);
        publish("TOKEN_REFRESHED", next);
        return next;
      } catch (error) {
        if (session === origin && error.code === "session_invalid") publish("SIGNED_OUT", null);
        throw error;
      } finally { refreshing = null; }
    })();
    return refreshing;
  }
  const storageListener = (event) => {
    if (event.key !== storageKey) return;
    let value = null;
    try { value = JSON.parse(event.newValue || "null"); } catch { /* invalid stored token */ }
    const identity = item => `${item?.user?.id || ""}:${item?.user?.email?.trim().toLowerCase() || ""}`;
    if (!value || identity(value) !== identity(session)) {
      pending = null;
      loginGeneration += 1;
    }
    publish(value ? "TOKEN_REFRESHED" : "SIGNED_OUT", value, false);
  };
  window.addEventListener("storage", storageListener);

  const auth = {
    async getSession() {
      try {
        if (session && session.expires_at * 1000 < Date.now() + 60000) await refresh();
        return { data: { session }, error: null };
      } catch (error) { return { data: { session }, error }; }
    },
    onAuthStateChange(callback) {
      listeners.add(callback);
      let live = true;
      queueMicrotask(async () => {
        const result = await auth.getSession();
        if (live) callback("INITIAL_SESSION", result.data.session);
      });
      return { data: { subscription: { unsubscribe() { live = false; listeners.delete(callback); } } } };
    },
    async signInWithOtp({ email }) {
      const generation = ++loginGeneration;
      pending = null;
      try {
        const username = email.trim().toLowerCase();
        let response = await call("InitiateAuth", { ClientId: clientId, AuthFlow: "USER_AUTH", AuthParameters: { USERNAME: username, PREFERRED_CHALLENGE: "EMAIL_OTP" } });
        if (response.ChallengeName === "SELECT_CHALLENGE") response = await call("RespondToAuthChallenge", {
          ClientId: clientId, ChallengeName: "SELECT_CHALLENGE", Session: response.Session,
          ChallengeResponses: { USERNAME: username, ANSWER: "EMAIL_OTP" } });
        if (response.ChallengeName !== "EMAIL_OTP") throw new Error("Email code login is unavailable. Contact the workspace owner.");
        if (generation !== loginGeneration) throw new Error("Sign-in was cancelled. Request a new code.");
        pending = { username: response.ChallengeParameters?.USERNAME || username, session: response.Session };
        return { error: null };
      } catch (error) { return { error }; }
    },
    async verifyOtp({ token }) {
      try {
        if (!pending) throw new Error("Request a new code first.");
        const challenge = pending;
        const response = await call("RespondToAuthChallenge", { ClientId: clientId, ChallengeName: "EMAIL_OTP", Session: challenge.session,
          ChallengeResponses: { USERNAME: challenge.username, EMAIL_OTP_CODE: token.trim() } });
        if (!response.AuthenticationResult) throw new Error("Sign-in could not be completed. Request a new code.");
        if (pending !== challenge) throw new Error("Sign-in was cancelled. Request a new code.");
        pending = null;
        publish("SIGNED_IN", fromTokens(response.AuthenticationResult));
        return { error: null };
      } catch (error) { return { error }; }
    },
    async signOut() {
      const origin = session;
      loginGeneration += 1;
      pending = null;
      publish("SIGNED_OUT", null);
      if (origin) { try { await call("GlobalSignOut", { AccessToken: origin.access_token }); } catch { /* local private state is already removed */ } }
      return { error: null };
    },
  };
  if (session) publish("INITIAL_SESSION", session, false);
  return { auth, dispose() { clearTimeout(timer); window.removeEventListener("storage", storageListener); listeners.clear(); } };
}
