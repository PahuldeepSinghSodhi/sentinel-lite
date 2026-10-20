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

  if (user) return <Workspace cloudUser={user} onSignOut={() => supabase.auth.signOut()} />;
  return <div className="cloud-entry"><div className="cloud-entry-card">
    <span className="cloud-logo"><Layers3 size={24} /> sentinel<span>.</span></span>
    <p className="eyebrow">PRIVATE PROCUREMENT WORKSPACE</p>
    <h1>Make every review traceable.</h1>
    <p className="cloud-lead">Upload your sources, investigate the exceptions, and keep a record of every decision.</p>
    {loading || (session && !error) ? <p role="status">Checking your invitation…</p> :
      session ? <><div className="notice error" role="alert">{error}</div>
        <button className="button secondary" onClick={() => supabase.auth.signOut()}>Sign out and try another account</button></> :
      <><div className="cloud-signin"><button className="button primary" onClick={() => signIn("google")}>Continue with Google <ArrowRight size={16} /></button>
        <button className="button secondary" onClick={() => signIn("github")}>Continue with GitHub <ArrowRight size={16} /></button></div>
        {error && <div className="notice error" role="alert">{error}</div>}</>}
    <div className="cloud-entry-footer"><span><LockKeyhole size={16} /> Invitation required</span>
      <span><ShieldCheck size={16} /> Private case files</span></div>
  </div></div>;
}
