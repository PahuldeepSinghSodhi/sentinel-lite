import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight, BookOpen, ChevronRight, Download, FileStack,
  Layers3, MessageSquareText, Plus, ShieldCheck, ShieldAlert,
} from "lucide-react";
import QueryTab from "./components/QueryTab";
import AnomalyTab from "./components/AnomalyTab";
import DocumentsTab from "./components/DocumentsTab";
import { api, downloadReport } from "./api";
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
const savedCaseKey = "sentinel-active-case";

export default function App() {
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
  const section = sections.find((item) => item.id === activeTab);

  function navigateTo(id) {
    setActiveTab(id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function openCaseSwitcher() {
    caseSwitcher.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    (caseSelect.current || newCaseButton.current)?.focus({ preventScroll: true });
  }

  async function loadCase(id) {
    const data = await api(`/cases/${id}`);
    setReview(data);
    localStorage.setItem(savedCaseKey, id);
    return data;
  }
  async function refreshCases() {
    const items = await api("/cases");
    setCases(items);
    const saved = localStorage.getItem(savedCaseKey);
    const selected = items.find((item) => item.id === saved) || items[0];
    if (selected) await loadCase(selected.id);
    else setReview(null);
  }
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
  }, []);
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
      navigateTo(demo ? "anomaly" : "documents");
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
          <div className="local-note"><ShieldCheck size={20} /><strong>Designed for local work</strong>
            <p>Files, review history, and your configured model stay in your local environment.</p></div>
          <button type="button" className="sidebar-footer" onClick={() => aboutDialog.current?.showModal()}
            title="About Sentinel Lite"><span className="workspace-avatar small">SL</span>
            <span>Sentinel Lite<small>About this workspace</small></span><ArrowUpRight className="sidebar-footer-arrow" size={15} /></button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb"><button type="button" onClick={() => navigateTo("documents")}>Workspace</button>
            <ChevronRight size={14} /><strong>{section.label}</strong></div>
          <button className={`connection ${connection}`} onClick={() => window.location.reload()} title="Refresh backend connection">
            <span />{connection === "connected" ? "Backend connected" : connection === "checking" ? "Connecting…" : "Backend offline"}
          </button>
        </header>
        <main id="main-content" className="main-content">
          <div className="page-heading"><div><p className="eyebrow">PROCUREMENT REVIEW</p><h1>{section.title}</h1>
            <p className="page-description">{section.description}</p></div>
            <span className="collection-tag"><BookOpen size={15} /> Local review</span></div>
          <section className="case-switcher panel" aria-label="Review case selection" ref={caseSwitcher}>
            <div><p className="eyebrow">CURRENT CASE</p><strong>{review?.name || "No review case yet"}</strong>
              <small>{review ? `${review.status === "active" ? "Active" : "Draft"} · Created ${new Date(review.created_at).toLocaleDateString()}` : "Create a case or open the sample to begin."}</small></div>
            <div className="case-switcher-actions">
              {cases.length > 0 && <select ref={caseSelect} aria-label="Select review case" value={review?.id || ""}
                onChange={async (event) => { try { const selected = await loadCase(event.target.value); setError("");
                  if (!selected.ready) navigateTo("documents"); } catch (err) { setError(err.message); } }}>
                {cases.map((item) => <option key={item.id} value={item.id}>{item.name} · {new Date(item.created_at).toLocaleDateString()}</option>)}
              </select>}
              <button ref={newCaseButton} type="button" className="button secondary" disabled={busy} onClick={() => createCase(false)}><Plus size={15} /> New case</button>
              <button className="button secondary" disabled={busy} onClick={() => createCase(true)}>Try sample <ArrowUpRight size={15} /></button>
            </div>
          </section>
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
          <footer className="page-footer"><span>Sentinel Lite · Built for thoughtful review</span><span>AI assists. You decide.</span></footer>
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
          <button type="button" className="button ghost" onClick={() => aboutDialog.current?.close()} aria-label="Close about Sentinel Lite">Close</button></div>
        <p className="eyebrow">ABOUT THE WORKSPACE</p><h2 id="about-title">Sentinel Lite</h2>
        <p>Review procurement transactions against approved rates, inspect evidence-backed findings, ask questions across the case, and download a report of your decisions.</p>
        <p>Case files and review history stay local. AI helps explain findings; your source rows and reviewer decisions remain the evidence.</p>
        <div className="about-dialog-actions">{sections.map(({ id, label }) =>
          <button type="button" className="button secondary" key={id} onClick={() => { aboutDialog.current?.close(); navigateTo(id); }}>
            {label}<ArrowUpRight size={14} /></button>)}</div>
      </dialog>
    </div>
  );
}
