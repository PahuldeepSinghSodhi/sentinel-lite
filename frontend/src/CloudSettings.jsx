import { useEffect, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { api } from "./api";

export default function CloudSettings({ user }) {
  const [settings, setSettings] = useState(null);
  const [storage, setStorage] = useState(null);
  const [provider, setProvider] = useState("ollama_cloud");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [invites, setInvites] = useState([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("reviewer");

  useEffect(() => {
    api("/me/model").then((value) => {
      setSettings(value);
      setProvider(value.provider || "ollama_cloud");
      setModel(value.model || value.choices.ollama_cloud[0]);
    }).catch((error) => setMessage(error.message));
    api("/me/storage").then(setStorage).catch(() => {});
    if (user.role === "admin") api("/admin/invites").then(setInvites).catch(() => {});
  }, [user.role]);

  async function save(event) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      setSettings(await api("/me/model", { method: "PUT", body: JSON.stringify({ provider, model, api_key: key }) }));
      setKey(""); setMessage("Model tested and saved. Your key will not be shown again.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true); setMessage("");
    try {
      await api("/me/model", { method: "DELETE" });
      setSettings({ ...settings, configured: false, provider: null, model: null });
      setMessage("Saved model key removed.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function invite(event) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await api("/admin/invites", { method: "PUT", body: JSON.stringify({ email: inviteEmail, role: inviteRole, enabled: true }) });
      setInvites(await api("/admin/invites")); setInviteEmail(""); setMessage("Invitation saved.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function toggleInvite(item) {
    setBusy(true); setMessage("");
    try {
      await api("/admin/invites", { method: "PUT", body: JSON.stringify({
        email: item.email, role: item.role, enabled: !item.enabled,
      }) });
      setInvites(await api("/admin/invites"));
      setMessage(item.enabled ? "Invitation revoked. API access stops immediately." : "Invitation restored.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }

  return <div className="cloud-settings">
    <p>Signed in as <strong>{user.email}</strong></p>
    {storage && <p>{(storage.used_bytes / 1048576).toFixed(1)} of {(storage.limit_bytes / 1048576).toFixed(0)} MB used · {storage.case_count} of {storage.case_limit} cases</p>}
    <h3>AI provider</h3>
    <p>Scanning requires no AI key. Document answers and requested investigation briefs send relevant excerpts to your chosen provider, which may charge for usage.</p>
    <p>{settings?.configured ? `Configured: ${settings.provider} · ${settings.model}` : "No AI model configured yet."}</p>
    {settings && <form onSubmit={save} className="settings-form">
      <label>Provider<select value={provider} onChange={(event) => {
        setProvider(event.target.value); setModel(settings.choices[event.target.value][0]);
      }}><option value="ollama_cloud">Ollama Cloud</option><option value="groq">Groq</option><option value="openai">OpenAI</option></select></label>
      <label>Model<select value={model} onChange={(event) => setModel(event.target.value)}>
        {settings.choices[provider].map((choice) => <option key={choice}>{choice}</option>)}</select></label>
      <label>Provider API key<input type="password" autoComplete="off" value={key}
        onChange={(event) => setKey(event.target.value)} placeholder="Paste a new key to test and save" /></label>
      <div className="settings-actions"><button className="button primary" disabled={busy || key.length < 8}>
        {busy && <Loader2 className="spin" size={15} />} Test and save</button>
        {settings.configured && <button type="button" className="button secondary" disabled={busy} onClick={remove}>
          <Trash2 size={15} /> Remove saved key</button>}</div>
    </form>}
    {user.role === "admin" && <section className="invite-settings"><h3>Invited reviewers</h3>
      <form onSubmit={invite} className="settings-form"><label>Email<input type="email" value={inviteEmail}
        onChange={(event) => setInviteEmail(event.target.value)} placeholder="reviewer@example.com" /></label>
        <label>Role<select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>
          <option value="reviewer">Reviewer</option><option value="admin">Administrator</option>
        </select></label>
        <button className="button secondary" disabled={busy || !inviteEmail}>Add invitation</button></form>
      <ul>{invites.map((item) => <li key={item.email}>{item.email} · {item.role} · {item.enabled ? "Active" : "Revoked"}
        <button type="button" className="button ghost" disabled={busy || item.email === user.email}
          onClick={() => toggleInvite(item)}>{item.enabled ? "Revoke" : "Restore"}</button></li>)}</ul>
    </section>}
    {message && <p role="status">{message}</p>}
  </div>;
}
