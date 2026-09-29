import { useRef, useState } from "react";
import { ArrowRight, BookOpen, Check, Copy, Loader2, MessageSquareText, Sparkles } from "lucide-react";
import { api } from "../api";
import ConfidenceMeter from "./ConfidenceMeter";
import EvidenceList from "./EvidenceList";
import AnswerPresentation from "./AnswerPresentation";

const suggestions = [
  "How many duplicate groups are in the latest scan, and which vendors and CSV rows are involved?",
  "Which vendors have rate violations, and where are the transaction and rate-card rows?",
  "What is the approved hourly rate for [vendor] [role]?",
  "What does the rate card say about [vendor]?",
  "What payment terms are stated in the contract?",
];

export default function QueryTab({ review, onChange, onViewFiles }) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const input = useRef(null);
  async function ask(event) {
    event.preventDefault();
    if (!review?.ready || !question.trim() || loading) return;
    setLoading(true);
    setError("");
    try {
      await api(`/cases/${review.id}/questions`, {
        method: "POST", body: JSON.stringify({ question: question.trim(), top_k: 5 }),
      });
      setQuestion("");
      await onChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }
  async function copyAnswer(item) {
    try {
      await navigator.clipboard.writeText(item.answer);
      setCopied(item.id);
    } catch {
      setError("Copy is unavailable in this browser. Select the answer to copy it.");
    }
  }
  if (!review?.ready) return <section className="panel gated-panel"><BookOpen size={35} />
    <h2>Prepare your sources first.</h2><p>Upload transactions and an approved rate card, then start the review to ask questions.</p>
    <button className="button secondary" onClick={onViewFiles}>Open source files</button></section>;
  const history = [...review.questions].reverse();
  return <div className="query-layout"><div className="query-main">
    <section className="panel composer"><div className="panel-heading"><span className="icon-label">
      <MessageSquareText size={19} /> Ask across your case</span>
      <span className="subtle-label">Uploaded files + latest anomaly scan</span></div>
      <form onSubmit={ask}><label className="sr-only" htmlFor="question">Your document question</label>
        <textarea ref={input} id="question" value={question} onChange={(event) => setQuestion(event.target.value)}
          placeholder="What would you like to know?" rows={4} disabled={loading}
          onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) ask(event); }} />
        <div className="composer-actions"><span><BookOpen size={15} /> Uses this case’s files and saved scan findings</span>
          <button className="button primary" disabled={loading || !question.trim()}>
            {loading ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
            {loading ? "Finding an answer…" : "Ask Sentinel"}<ArrowRight size={16} /></button></div>
      </form></section>
    {error && <div className="notice error" role="alert">{error}</div>}
    {!history.length && <section className="suggestions"><div className="section-label"><span>A PLACE TO START</span><span>Try a question</span></div>
      <div className="suggestion-grid">{suggestions.filter((item) => review.files.contract || !item.includes("contract"))
        .map((item) => <button className="suggestion" key={item} onClick={() => { setQuestion(item); input.current?.focus(); }}>
          <small>CASE QUESTION</small><p>{item}</p><ArrowRight size={17} /></button>)}</div></section>}
    {history.map((item) => <section className="panel answer-panel" aria-label="Saved answer" key={item.id}>
      <div className="panel-heading"><span className="icon-label">
        {item.presentation?.kind === "scan" ? <BookOpen size={19} /> : <Sparkles size={19} />}
        {item.presentation?.kind === "scan" ? "Scan-backed answer" : "Document answer"}</span>
        <button className="button ghost small-button" onClick={() => copyAnswer(item)}>
          {copied === item.id ? <Check size={15} /> : <Copy size={15} />}{copied === item.id ? "Copied" : "Copy"}</button></div>
      <p className="answered-question">{item.question}</p><AnswerPresentation item={item} />
      {item.confidence?.basis === "latest_scan" && !item.presentation && <p className="answer-basis">Based on the latest scan at the time of this question: {new Date(item.confidence.scan_created_at).toLocaleString()}. Counts come from saved findings, not AI estimates.</p>}
      {item.confidence?.overall_confidence !== undefined && <ConfidenceMeter score={item.confidence.overall_confidence} />}
      <EvidenceList caseId={review.id} items={item.sources} title="Source rows and passages to inspect" />
      <p className="answer-timestamp">Asked {new Date(item.created_at).toLocaleString()}</p>
    </section>)}
  </div><aside className="context-rail"><div className="context-card"><span className="rail-icon"><BookOpen size={23} /></span>
    <p className="eyebrow">A LITTLE CONTEXT</p><h2>Answers with inspectable sources.</h2>
    <p>Ask about a saved scan or a document. Open the evidence beneath an answer to inspect CSV rows, TXT lines, or PDF pages. Run a scan first for anomaly counts.</p>
    <button className="text-button" onClick={onViewFiles}>Explore case files <ArrowRight size={16} /></button>
  </div></aside></div>;
}
