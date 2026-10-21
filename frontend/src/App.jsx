import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight, BookOpen, ChevronRight, Download, FileStack,
  Layers3, MessageSquareText, Plus, ShieldCheck, ShieldAlert, Settings2, Trash2,
} from "lucide-react";
import QueryTab from "./components/QueryTab";
import AnomalyTab from "./components/AnomalyTab";
import DocumentsTab from "./components/DocumentsTab";
import { api, downloadReport } from "./api";
import { CLOUD_MODE } from "./cloud";
import CloudSettings from "./CloudSettings";
import "./App.css";
import "./refinements.css";

const sections = [
  { id: "documents", label: "Source files", icon: FileStack,
    title: "Start with reliable sources.", description: "Upload transactions, approved rates, and an optional vendor contract." },
  { id: "anomaly", label: "Anomaly review", icon: ShieldAlert,
    title: "Bring the exceptions into focus.", description: "Review unusual charges and record a decision for every finding." },
  { id: "query", label: "Ask documents", icon: MessageSquareText,
    title: "Clarity starts with a question.", description: "Ask across uploaded files and saved anomaly findings, with inspectable source locations." },
];
export default function App({ cloudUser, onSignOut }) {
  const savedCaseKey = CLOUD_MODE ? `sentinel-active-case-${cloudUser?.id}` : "sentinel-active-case";
  const [activeTab, setActiveTab] = useState("documents");
  const [cases, setCases] = useState([]);
  const [review, setReview] = useState(null);
  const [connection, setConnection] = useState("checking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const caseSwitcher = useRef(null);
  const caseSelect = useRef(null);
  const newCaseButton = useRef(null);
  const aboutDialog = useRef(null);
  const settingsDialog = useRef(null);
  const section = sections.find((item) => item.id === activeTab);

  function navigateTo(id) {
    setActiveTab(id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function openCaseSwitcher() {
    caseSwitcher.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    (caseSelect.current || newCaseButton.current)?.focus({ preventScroll: true });
  }

  const loadCase = useCallback(async (id) => {
    const data = await api(`/cases/${id}`);
    setReview(data);
    localStorage.setItem(savedCaseKey, id);
    return data;
  }, [savedCaseKey]);
  const refreshCases = useCallback(async () => {
    const items = await api("/cases");
    setCases(items);
    const saved = localStorage.getItem(savedCaseKey);
    const selected = items.find((item) => item.id === saved) || items[0];
    if (selected) await loadCase(selected.id);
    else setReview(null);
  }, [loadCase, savedCaseKey]);
  useEffect(() => {
    let mounted = true;
    async function initialize() {
      try {
        await api("/", { timeout: 5000 });
        if (!mounted) return;
        setConnection("connected");
        await refreshCases();
      } catch (err) {
        if (mounted) {
          setConnection("offline");
          setError(err.message);
        }
      }
    }
    initialize();
    return () => { mounted = false; };
  }, [refreshCases]);
  useEffect(() => {
    if (!CLOUD_MODE || !review?.id || !["queued", "running"].includes(review.job?.status)) return;
    let stopped = false;
    let timer;
    const caseId = review.id;
    async function poll() {
      try {
        const item = await loadCase(caseId);
        if (!stopped && item.job?.status === "completed") await refreshCases();
      } catch (err) {
        if (!stopped) setError(err.message);
      } finally {
        // Wait for the previous request to finish before scheduling another.
        if (!stopped) timer = window.setTimeout(poll, 5000);
      }
    }
    timer = window.setTimeout(poll, 5000);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [review?.id, review?.job?.status, loadCase, refreshCases]);
  async function createCase(demo = false) {
    setBusy(true);
    setError("");
    try {
      const data = await api(demo ? "/cases/demo" : "/cases", {
        method: "POST",
        ...(demo ? {} : { body: JSON.stringify({ name: `Review ${new Date().toLocaleDateString()}` }) }),
      });
      await refreshCases();
      await loadCase(data.id);
      navigateTo(demo && !CLOUD_MODE ? "anomaly" : "documents");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function exportReport() {
    if (!review?.can_report) return;
    setBusy(true);
    setError("");
    try {
      await downloadReport(review.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  async function deleteCase() {
    if (!review || !window.confirm(`Delete ${review.name} and all its files and review history? This cannot be undone.`)) return;
    setBusy(true); setError("");
    try {
      await api(`/cases/${review.id}`, { method: "DELETE" });
      localStorage.removeItem(savedCaseKey);
      setReview(null);
      await refreshCases();
      navigateTo("documents");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return (
    <div className="workspace">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar">
        <button type="button" className="brand" onClick={() => navigateTo("documents")} aria-label="Go to Source files">
          <span className="brand-mark"><Layers3 size={22} strokeWidth={1.8} /></span>
          <span>sentinel<span className="brand-dot">.</span></span>
        </button>
        <button type="button" className="workspace-label" onClick={openCaseSwitcher} title="Choose or create a review case">
          <span className="workspace-avatar">S</span>
          <span>Procurement workspace<small>Choose a review case</small></span>
        </button>
        <p className="nav-caption">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {sections.map(({ id, label, icon: Icon }) => (
            <button type="button" key={id} className={`nav-item ${activeTab === id ? "active" : ""}`}
              onClick={() => navigateTo(id)} aria-current={activeTab === id ? "page" : undefined}>
              <Icon size={19} strokeWidth={1.7} /><span>{label}</span>
              {activeTab === id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note"><ShieldCheck size={20} /><strong>{CLOUD_MODE ? "Private cloud review" : "Designed for local work"}</strong>
            <p>{CLOUD_MODE ? "Your cases stay private to your invited account. AI excerpts go to your chosen provider." :
              "Files, review history, and your configured model stay in your local environment."}</p></div>
          <button type="button" className="sidebar-footer" onClick={() => aboutDialog.current?.showModal()}
            title="About Sentinel"><span className="workspace-avatar small">SL</span>
            <span>Sentinel<small>About this workspace</small></span><ArrowUpRight className="sidebar-footer-arrow" size={15} /></button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb"><button type="button" onClick={() => navigateTo("documents")}>Workspace</button>
            <ChevronRight size={14} /><strong>{section.label}</strong></div>
          <button className={`connection ${connection}`} onClick={() => window.location.reload()} title="Refresh backend connection">
            <span />{connection === "connected" ? "Backend connected" : connection === "checking" ? "Connecting…" : "Backend offline"}
          </button>
          {CLOUD_MODE && <button className="button ghost cloud-settings-button" onClick={() => settingsDialog.current?.showModal()}>
            <Settings2 size={17} /> Settings</button>}
        </header>
        <main id="main-content" className="main-content">
          <div className="page-heading"><div><p className="eyebrow">PROCUREMENT REVIEW</p><h1>{section.title}</h1>
            <p className="page-description">{section.description}</p></div>
            <span className="collection-tag"><BookOpen size={15} /> {CLOUD_MODE ? "Private cloud case" : "Local review"}</span></div>
          <section className="case-switcher panel" aria-label="Review case selection" ref={caseSwitcher}>
            <div><p className="eyebrow">CURRENT CASE</p><strong>{review?.name || "No review case yet"}</strong>
              <small>{review ? `${review.status === "active" ? "Active" : review.status === "starting" ? "Preparing" : "Draft"} · Created ${new Date(review.created_at).toLocaleDateString()}` : "Create a case or open the sample to begin."}</small></div>
            <div className="case-switcher-actions">
              {cases.length > 0 && <select ref={caseSelect} aria-label="Select review case" value={review?.id || ""}
                onChange={async (event) => { try { const selected = await loadCase(event.target.value); setError("");
                  if (!selected.ready) navigateTo("documents"); } catch (err) { setError(err.message); } }}>
                {cases.map((item) => <option key={item.id} value={item.id}>{item.name} · {new Date(item.created_at).toLocaleDateString()}</option>)}
              </select>}
              <button ref={newCaseButton} type="button" className="button secondary" disabled={busy} onClick={() => createCase(false)}><Plus size={15} /> New case</button>
              <button className="button secondary" disabled={busy} onClick={() => createCase(true)}>Try sample <ArrowUpRight size={15} /></button>
              {CLOUD_MODE && review && <button className="button ghost case-delete" disabled={busy || ["queued", "running"].includes(review.job?.status)}
                onClick={deleteCase}><Trash2 size={15} /> Delete case</button>}
            </div>
          </section>
          {CLOUD_MODE && ["queued", "running"].includes(review?.job?.status) &&
            <div className="notice" role="status">{review.job.kind === "start" ? "Preparing case files and search index" : "Scanning transactions"}… You can leave this page; progress is saved.</div>}
          {CLOUD_MODE && review?.job?.status === "failed" && <div className="notice error" role="alert">{review.job.error}</div>}
          {error && <div className="notice error" role="alert">{error}</div>}
          <div hidden={activeTab !== "documents"}>
            <DocumentsTab review={review} onChange={() => loadCase(review.id)} onStart={() => navigateTo("anomaly")}
              onNewCase={() => createCase(false)} busy={busy} />
          </div>
          <div hidden={activeTab !== "anomaly"}>
            <AnomalyTab review={review} onChange={() => loadCase(review.id)} onViewFiles={() => navigateTo("documents")} />
          </div>
          <div hidden={activeTab !== "query"}>
            <QueryTab review={review} onChange={() => loadCase(review.id)} onViewFiles={() => navigateTo("documents")} />
          </div>
          <footer className="page-footer"><span>Sentinel · Built for thoughtful review</span><span>AI assists. You decide.</span></footer>
        </main>
        <div className="report-bar">
          <div><strong>Case report</strong><small>{review?.can_report ? `${review.scans.length} scans · ${review.questions.length} questions saved` : "Run a scan or ask a question to create a report"}</small></div>
          <button className="button primary" disabled={!review?.can_report || busy} onClick={exportReport}>
            <Download size={16} /> Download report
          </button>
        </div>
      </div>
      <dialog ref={aboutDialog} className="about-dialog" aria-labelledby="about-title">
        <div className="about-dialog-heading"><span className="brand-mark"><Layers3 size={21} /></span>
          <button type="button" className="button ghost" onClick={() => aboutDialog.current?.close()} aria-label="Close about Sentinel">Close</button></div>
        <p className="eyebrow">ABOUT THE WORKSPACE</p><h2 id="about-title">Sentinel</h2>
        <p>Review procurement transactions against approved rates, inspect evidence-backed findings, ask questions across the case, and download a report of your decisions.</p>
        <p>{CLOUD_MODE ? "Case files and history are private to your account. Your chosen AI provider receives relevant excerpts when you ask for an answer or brief." :
          "Case files and review history stay local. AI helps explain findings; your source rows and reviewer decisions remain the evidence."}</p>
        <div className="about-dialog-actions">{sections.map(({ id, label }) =>
          <button type="button" className="button secondary" key={id} onClick={() => { aboutDialog.current?.close(); navigateTo(id); }}>
            {label}<ArrowUpRight size={14} /></button>)}</div>
      </dialog>
      {CLOUD_MODE && <dialog ref={settingsDialog} className="about-dialog settings-dialog" aria-labelledby="settings-title">
        <div className="about-dialog-heading"><h2 id="settings-title">Workspace settings</h2>
          <button className="button ghost" onClick={() => settingsDialog.current?.close()}>Close</button></div>
        <CloudSettings user={cloudUser} />
        <button className="button secondary" onClick={onSignOut}>Sign out</button>
      </dialog>}
    </div>
  );
}
