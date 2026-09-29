import { useState } from "react";
import { ArrowDown, FileSearch, Info } from "lucide-react";

function InlineText({ text }) {
  return String(text).split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part,
  );
}

export function FormattedAnswer({ text }) {
  const blocks = String(text || "").split(/\n\s*\n/).filter(Boolean);
  return <div className="formatted-answer">{blocks.map((block, index) => {
    const lines = block.split("\n").filter(Boolean);
    if (lines.every((line) => /^\s*[-*]\s+/.test(line)))
      return <ul key={index}>{lines.map((line, item) =>
        <li key={item}><InlineText text={line.replace(/^\s*[-*]\s+/, "")} /></li>)}</ul>;
    return <p key={index}>{lines.map((line, item) =>
      <span key={item}>{item > 0 && <br />}<InlineText text={line} /></span>)}</p>;
  })}</div>;
}

function FindingDetails({ finding }) {
  const decision = finding.decision?.replaceAll("_", " ") || "Not reviewed";
  return <details className="insight-finding">
    <summary><span>{finding.label}</span><span className="insight-row-ref">
      {finding.rows.length ? `Rows ${finding.rows.join(", ")}` : "View details"}</span></summary>
    <div className="insight-finding-body">
      <p>{finding.description}</p>
      {finding.details?.billed_rate !== undefined && <p className="rate-comparison">
        Billed {finding.details.billed_rate} · Approved {finding.details.approved_rate}
        {finding.details.difference_percentage !== undefined && ` · ${finding.details.difference_percentage.toFixed(1)}% over`}
      </p>}
      {finding.calculation && <p><strong>Calculation</strong> {finding.calculation}</p>}
      {finding.rule && <p><strong>Rule</strong> {finding.rule}</p>}
      <p><strong>Decision</strong> {decision}{finding.note && ` · ${finding.note}`}</p>
    </div>
  </details>;
}

export default function AnswerPresentation({ item }) {
  const [showAll, setShowAll] = useState(false);
  const data = item.presentation;
  if (data?.kind !== "scan") {
    if (item.confidence?.basis === "latest_scan" && item.answer.includes("\n")) {
      const [summary, ...details] = item.answer.split("\n");
      return <div className="legacy-answer"><p>{summary}</p>
        <details className="full-answer"><summary>View saved finding details</summary>
          <pre>{details.join("\n")}</pre></details></div>;
    }
    return <FormattedAnswer text={item.answer} />;
  }

  const groups = showAll ? data.groups : data.groups.slice(0, 4);
  return <div className="insight-answer">
    <div className="insight-lead">
      <span className="insight-eyebrow"><FileSearch size={14} /> FROM THE ANOMALY REVIEW</span>
      <h3>{data.summary}</h3>
      <p>{data.caveat}</p>
    </div>
    <div className="insight-metrics">{data.metrics.map(({ label, value }) =>
      <div className="insight-metric" key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
    {data.groups.length > 0 && <div className="insight-vendors">
      <div className="insight-section-heading"><strong>Where the findings are</strong>
        <span>{data.groups.length} vendor{data.groups.length === 1 ? "" : "s"} shown</span></div>
      {groups.map((group) => <div className="insight-vendor" key={group.vendor}>
        <div className="insight-vendor-header"><span className="vendor-monogram">{group.vendor.slice(0, 1).toUpperCase()}</span>
          <div><strong>{group.vendor}</strong><small>{group.finding_count} finding{group.finding_count === 1 ? "" : "s"}</small></div>
          <span className="vendor-rows">CSV rows {group.rows.join(", ") || "unavailable"}</span></div>
        {group.findings.map((finding, index) => <FindingDetails finding={finding} key={`${finding.type}-${index}`} />)}
      </div>)}
      {data.groups.length > 4 && <button type="button" className="show-more-vendors" onClick={() => setShowAll(!showAll)}>
        {showAll ? "Show fewer vendors" : `Show all ${data.groups.length} vendors`}<ArrowDown className={showAll ? "up" : ""} size={15} />
      </button>}
      {data.truncated && <p className="insight-note"><Info size={14} /> Showing the first 100 findings here. The full scan remains in Anomaly review and the case report.</p>}
    </div>}
    {data.groups.length === 0 && <p className="insight-empty">No matching findings in that scan. Try another vendor or a broader question.</p>}
    {data.document_answer && <section className="document-synthesis"><span className="insight-eyebrow">FROM UPLOADED DOCUMENTS · AI-GENERATED</span>
      <FormattedAnswer text={data.document_answer} />
      <p>Check the retrieved passages below before relying on this interpretation.</p>
    </section>}
    <p className="insight-scan-time">Based on the latest scan at the time of this question · {new Date(data.scan_created_at).toLocaleString()}</p>
    <details className="full-answer"><summary>Read the full saved answer</summary><pre>{item.answer}</pre></details>
  </div>;
}
