import { useEffect, useState } from "react";
import { ArrowRight, Layers3, LockKeyhole, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { supabase } from "./cloud";
import Workspace from "./App";

export default function CloudShell() {
  const [session, setSession] = useState(null);
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [emailSent, setEmailSent] = useState(false);
  const [sending, setSending] = useState(false);
  const googleEnabled = import.meta.env.VITE_ENABLE_GOOGLE_AUTH === "true";
  const githubEnabled = import.meta.env.VITE_ENABLE_GITHUB_AUTH === "true";

  useEffect(() => {
    let live = true;
    supabase.auth.getSession().then(({ data }) => {
      if (live) { setSession(data.session); setLoading(false); }
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next); setUser(null); setError(""); setLoading(false);
    });
    return () => { live = false; listener.subscription.unsubscribe(); };
  }, []);

  useEffect(() => {
    if (!session) return;
    let live = true;
    api("/me").then((result) => { if (live) setUser(result); })
      .catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [session]);

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

  if (user) return <Workspace cloudUser={user} onSignOut={() => supabase.auth.signOut()} />;
  return <div className="cloud-entry"><div className="cloud-entry-card">
    <span className="cloud-logo"><Layers3 size={24} /> sentinel<span>.</span></span>
    <p className="eyebrow">PRIVATE PROCUREMENT WORKSPACE</p>
    <h1>Make every review traceable.</h1>
    <p className="cloud-lead">Upload your sources, investigate the exceptions, and keep a record of every decision.</p>
    {loading || (session && !error) ? <p role="status">Checking your invitation…</p> :
      session ? <><div className="notice error" role="alert">{error}</div>
        <button className="button secondary" onClick={() => supabase.auth.signOut()}>Sign out and try another account</button></> :
      <><div className="cloud-signin">
        {emailSent ? <p role="status">Check your inbox for a sign-in link. Open it on this device to enter your workspace.</p> :
          <form className="cloud-email-form" onSubmit={emailSignIn}>
            <label htmlFor="cloud-email">Invited email</label>
            <input id="cloud-email" type="email" autoComplete="email" required value={email}
              onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
            <button className="button primary" type="submit" disabled={sending}>
              {sending ? "Sending link…" : "Email me a sign-in link"} <ArrowRight size={16} />
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
