import { useEffect, useRef, useState } from "react";
import { ArrowRight, Layers3, LockKeyhole, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { supabase, CLOUD_PROVIDER } from "./cloud";
import Workspace from "./App";
import { accountIdentity, subscribeAccessFailure } from "./access";

export default function CloudShell() {
  const [session, setSession] = useState(null);
  const [approval, setApproval] = useState(null);
  const [epoch, setEpoch] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [emailSent, setEmailSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [code, setCode] = useState("");
  const latest = useRef({ session: null, epoch: 0, denial: 0 });
  const pending = useRef(null);
  const identity = accountIdentity(session);
  const verificationKey = JSON.stringify([identity, epoch, attempt]);
  const user = approval?.key === verificationKey ? approval.user : null;
  const googleEnabled = import.meta.env.VITE_ENABLE_GOOGLE_AUTH === "true";
  const githubEnabled = import.meta.env.VITE_ENABLE_GITHUB_AUTH === "true";

  useEffect(() => {
    let live = true;
    const unsubscribeFailure = subscribeAccessFailure(({ error: issue, session: origin }) => {
      const current = latest.current.session;
      if (!live || accountIdentity(current) !== accountIdentity(origin)
          || current?.access_token !== origin.access_token) return;
      latest.current.denial += 1;
      setApproval(null);
      setError(issue.message);
    });
    // INITIAL_SESSION restores the session; no competing getSession initialization.
    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => {
      if (!live) return;
      if (accountIdentity(latest.current.session) !== accountIdentity(next)) {
        latest.current.epoch += 1;
        setApproval(null);
        setError("");
        setEmailSent(false);
      }
      latest.current.session = next;
      setEpoch(latest.current.epoch);
      setSession(next);
      setLoading(false);
    });
    return () => { live = false; unsubscribeFailure(); listener.subscription.unsubscribe(); };
  }, []);

  useEffect(() => {
    if (!identity) return;
    let live = true;
    const denial = latest.current.denial;
    const isCurrent = () => latest.current.epoch === epoch;
    // Reuse the same attempt during Strict Mode's effect replay.
    if (pending.current?.key !== verificationKey) {
      const promise = Promise.resolve().then(async () => {
        while (isCurrent()) {
          const origin = latest.current.session;
          try {
            return await api("/me", { accessSession: origin });
          } catch (issue) {
            // A refresh may complete while the first verification is in flight.
            if (isCurrent() && issue.code === "session_invalid"
                && origin.access_token !== latest.current.session?.access_token) continue;
            throw issue;
          }
        }
      });
      pending.current = { key: verificationKey, promise };
    }
    pending.current.promise.then((result) => {
      if (live && isCurrent() && latest.current.denial === denial && result) {
        setApproval({ key: verificationKey, user: result });
        setError("");
      }
    }).catch((issue) => {
      if (live && isCurrent() && latest.current.denial === denial) setError(issue.message);
    });
    return () => { live = false; };
  }, [identity, epoch, attempt, verificationKey]);

  function retryVerification() {
    setError("");
    setAttempt((previous) => previous + 1);
  }

  async function signIn(provider) {
    setError("");
    const { error: issue } = await supabase.auth.signInWithOAuth({
      provider, options: { redirectTo: window.location.origin },
    });
    if (issue) setError(issue.message);
  }

  async function emailSignIn(event) {
    event.preventDefault();
    setError("");
    setSending(true);
    const { error: issue } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: window.location.origin },
    });
    setSending(false);
    if (issue) setError(issue.message);
    else setEmailSent(true);
  }

  async function verifyCode(event) {
    event.preventDefault();
    setError("");
    setSending(true);
    const { error: issue } = await supabase.auth.verifyOtp({ email: email.trim(), token: code, type: "email" });
    setSending(false);
    if (issue) setError(issue.message);
  }

  if (user) return <Workspace key={identity} cloudUser={user} onSignOut={() => supabase.auth.signOut()} />;
  return <div className="cloud-entry"><div className="cloud-entry-card">
    <span className="cloud-logo"><Layers3 size={24} /> sentinel<span>.</span></span>
    <p className="eyebrow">PRIVATE PROCUREMENT WORKSPACE</p>
    <h1>Make every review traceable.</h1>
    <p className="cloud-lead">Upload your sources, investigate the exceptions, and keep a record of every decision.</p>
    {loading || (session && !error) ? <p role="status">Checking your invitation…</p> :
      session ? <><div className="notice error" role="alert">{error}</div>
        <button className="button primary" onClick={retryVerification}>Retry verification</button>
        <button className="button secondary" onClick={() => supabase.auth.signOut()}>Sign out and try another account</button></> :
      <><div className="cloud-signin">
        {emailSent ? CLOUD_PROVIDER === "aws" ? <form className="cloud-email-form" onSubmit={verifyCode}>
          <p role="status">Enter the verification code sent to your invited email.</p>
          <label htmlFor="cloud-code">Email verification code</label>
          <input id="cloud-code" value={code} onChange={event => setCode(event.target.value)} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6,8}" maxLength={8} required />
          <button className="button primary" type="submit" disabled={sending}>{sending ? "Checking code…" : "Open workspace"}</button>
          <button className="button secondary" type="button" onClick={() => { setEmailSent(false); setCode(""); setError(""); }}>Use another email or request a new code</button>
        </form> : <p role="status">Check your inbox for a sign-in link. Open it on this device to enter your workspace.</p> :
          <form className="cloud-email-form" onSubmit={emailSignIn}>
            <label htmlFor="cloud-email">Invited email</label>
            <input id="cloud-email" type="email" autoComplete="email" required value={email}
              onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            <button className="button primary" type="submit" disabled={sending}>
              {sending ? "Sending…" : CLOUD_PROVIDER === "aws" ? "Email me a sign-in code" : "Email me a sign-in link"} <ArrowRight size={16} />
            </button>
          </form>}
        {googleEnabled && <button className="button secondary" onClick={() => signIn("google")}>Continue with Google <ArrowRight size={16} /></button>}
        {githubEnabled && <button className="button secondary" onClick={() => signIn("github")}>Continue with GitHub <ArrowRight size={16} /></button>}
      </div>
        {error && <div className="notice error" role="alert">{error}</div>}</>}
    <div className="cloud-entry-footer"><span><LockKeyhole size={16} /> Invitation required</span>
      <span><ShieldCheck size={16} /> Private case files</span></div>
  </div></div>;
}
