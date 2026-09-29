import { useState } from "react";
import { ArrowRight, CheckCheck, FileSearch, Loader2, Play, ShieldAlert, Sparkles } from "lucide-react";
import { api } from "../api";
import EvidenceList from "./EvidenceList";

const labels = { duplicate: "Possible duplicate", outlier_zscore: "Statistical outlier",
  outlier_iqr: "Outside expected range", rate_violation: "Rate discrepancy",
  missing_rate: "No approved rate" };
const decisions = [
  ["", "Choose a decision"], ["investigate", "Investigate"],
  ["approved_exception", "Approved exception"], ["false_alarm", "False alarm"],
];

function FindingCard({ finding, review, onChange, ordinal }) {
  const [decision, setDecision] = useState(finding.decision || "");
  const [note, setNote] = useState(finding.note || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [explanation, setExplanation] = useState("");
  const [explaining, setExplaining] = useState(false);
  async function save() {
    setSaving(true);
    setError("");
    try {
      await api(`/cases/${review.id}/findings/${finding.id}`, {
        method: "PATCH", body: JSON.stringify({ decision, note }),
      });
      await onChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }
  async function explain() {
    setExplaining(true);
    setError("");
    try {
      const result = await api("/explain_anomaly", {
        method: "POST",
        body: JSON.stringify({ type: finding.type, severity: finding.severity,
          description: finding.description, details: finding.details, row_indices: finding.row_indices }),
      });
      setExplanation(result.explanation);
    } catch (err) {
      setError(err.message);
    } finally {
      setExplaining(false);
    }
  }
  return <article className="finding">
    <div className="finding-top"><span className={`severity ${finding.severity}`}>{finding.severity}</span>
      <h3>{labels[finding.type] || finding.type}</h3><span className="finding-id">#{ordinal}</span></div>
    <p>{finding.description}</p>
    <div className="finding-rule"><strong>Rule</strong> {finding.rule}<br /><strong>Calculation</strong> {finding.calculation}</div>
    <EvidenceList caseId={review.id} items={finding.evidence} />
    <div className="decision-form">
      <label>Reviewer decision
        <select value={decision} onChange={(event) => setDecision(event.target.value)}>
          {decisions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select>
      </label>
      <label>Note {decision === "approved_exception" ? "(required)" : "(optional)"}
        <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={2}
          placeholder="Explain your review decision" /></label>
      <button className="button primary" disabled={!decision || saving || (decision === "approved_exception" && !note.trim())}
        onClick={save}>{saving ? <Loader2 className="spin" size={15} /> : <CheckCheck size={15} />}
        {saving ? "Saving…" : finding.decision ? "Update decision" : "Save decision"}</button>
    </div>
    {finding.decided_at && <small className="saved-decision">Saved {new Date(finding.decided_at).toLocaleString()}</small>}
    <button className="text-button explain-button" disabled={explaining} onClick={explain}>
      {explaining ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}
      {explaining ? "Preparing explanation…" : "Explain this finding"}<ArrowRight size={14} />
    </button>
    {explanation && <div className="explanation"><strong><Sparkles size={15} /> AI explanation</strong>
      <p>{explanation}</p></div>}
    {error && <div className="notice error" role="alert">{error}</div>}
  </article>;
}

export default function AnomalyTab({ review, onChange, onViewFiles }) {
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  async function scan() {
    setScanning(true);
    setError("");
    try {
      await api(`/cases/${review.id}/scans`, { method: "POST" });
      await onChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  }
  if (!review?.ready) return <section className="panel gated-panel"><ShieldAlert size={35} />
    <h2>Files first, findings next.</h2><p>Upload transactions and an approved rate card, then start the review.</p>
    <button className="button secondary" onClick={onViewFiles}>Open source files</button></section>;
  const scans = [...review.scans].reverse();
  const latest = scans[0];
  const total = scans.reduce((count, item) => count + item.findings.length, 0);
  function jumpTo(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  const metrics = latest ? [
    { label: "Transactions reviewed", value: latest.transactions_analyzed, hint: "View source files", action: onViewFiles },
    { label: "Findings this scan", value: latest.findings.length, hint: "View latest scan", action: () => jumpTo(`scan-${latest.id}`) },
    { label: "Total findings", value: total, hint: "View review history", action: () => jumpTo("review-history") },
    { label: "Scans", value: scans.length, hint: "View scan history", action: () => jumpTo("review-history") },
  ] : [];
  return <div className="anomaly-layout">
    <section className="panel scan-bar"><div className="scan-title"><span className="shortcut-icon"><ShieldAlert size={23} /></span>
      <div><h2>Transaction review</h2><p>Scan this case’s uploaded transactions against its approved rates.</p></div></div>
      <button className="button primary" disabled={scanning} onClick={scan}>
        {scanning ? <Loader2 className="spin" size={16} /> : <Play size={15} />}
        {scanning ? "Scanning…" : latest ? "Run another scan" : "Run scan"}</button></section>
    {error && <div className="notice error" role="alert">{error}</div>}
    {!latest && <section className="panel scan-empty"><div className="empty-illustration"><div /><span><FileSearch size={38} /></span></div>
      <p className="eyebrow">READY TO REVIEW</p><h2>Know where to look first.</h2>
      <p>Run a scan to identify duplicates, unusual values, and rate discrepancies.</p></section>}
    {latest && <><div className="metric-grid">
      {metrics.map(({ label, value, hint, action }) =>
        <button type="button" className="panel metric metric-link" key={label} onClick={action}
          aria-label={`${label}: ${value}. ${hint}`}>
          <span>{label}</span><strong>{value}</strong><small>{hint} <ArrowRight size={12} /></small></button>)}
    </div>
      <section className="panel findings-panel" id="review-history"><div className="findings-toolbar"><h2>Review history <span className="count-pill">{total}</span></h2>
        <div className="filter-group" aria-label="Filter findings by severity">
          {["all", "high", "medium", "low"].map((value) =>
            <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}
              aria-pressed={filter === value}>{value === "all" ? "All findings" : value}</button>)}
        </div></div>
        {scans.map((item, scanIndex) => {
          const visible = item.findings.filter((finding) => filter === "all" || finding.severity === filter);
          return <div className="scan-group" id={`scan-${item.id}`} key={item.id}>
            <div className="scan-group-heading"><strong>Scan {scans.length - scanIndex}</strong>
              <span>{new Date(item.created_at).toLocaleString()} · {item.transactions_analyzed} transactions · {item.duration_ms} ms</span></div>
            {visible.length ? visible.map((finding, index) => <FindingCard key={finding.id} finding={finding}
              review={review} onChange={onChange} ordinal={index + 1} />)
              : <div className="empty-filter"><CheckCheck size={25} /><p>{item.findings.length ? "No findings match this filter." : "No findings in this scan."}</p></div>}
          </div>;
        })}
      </section><p className="review-note">Findings are signals for human review. Confirm any approved exceptions before taking action.</p></>}
  </div>;
}
