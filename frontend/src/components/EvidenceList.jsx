import { useState } from "react";
import { FileSearch, Loader2 } from "lucide-react";
import { api } from "../api";

export default function EvidenceList({ caseId, items = [], title = "Supporting evidence" }) {
  const [opened, setOpened] = useState({});
  const [loading, setLoading] = useState({});
  const [showAll, setShowAll] = useState(false);
  async function show(index, item) {
    if (opened[index]) {
      setOpened((previous) => ({ ...previous, [index]: null }));
      return;
    }
    if (!item.kind) return;
    const params = new URLSearchParams();
    if (item.page) params.set("page", item.page);
    if (item.row_number) params.set("row", item.row_number);
    if (item.line_start) params.set("line_start", item.line_start);
    if (item.line_end) params.set("line_end", item.line_end);
    setLoading((previous) => ({ ...previous, [index]: true }));
    try {
      const data = await api(`/cases/${caseId}/source/${item.kind}?${params}`);
      setOpened((previous) => ({ ...previous, [index]: data.text }));
    } catch (error) {
      setOpened((previous) => ({ ...previous, [index]: `Could not open source: ${error.message}` }));
    } finally {
      setLoading((previous) => ({ ...previous, [index]: false }));
    }
  }
  if (!items.length) return null;
  const visible = showAll ? items : items.slice(0, 5);
  return (
    <div className="evidence-list">
      <p className="evidence-title">{title} <span>({items.length})</span></p>
      {visible.map((item, index) => {
        const canOpen = Boolean(item.kind && (item.page || item.row_number || (item.line_start && item.line_end)));
        return <div className="evidence-item" key={`${item.source}-${item.location}-${index}`}>
          {canOpen ? <button type="button" className="evidence-link" onClick={() => show(index, item)}
            aria-expanded={Boolean(opened[index])}>
            {loading[index] ? <Loader2 className="spin" size={15} /> : <FileSearch size={15} />}
            <span>{item.source} · {item.location || "Location unavailable"}</span>
            <small>{opened[index] ? "Hide" : "Open source"}</small>
          </button> : <div className="evidence-link evidence-unavailable">
            <FileSearch size={15} /><span>{item.source} · {item.location || "Location unavailable"}</span>
            <small>Preview unavailable</small></div>}
          {item.columns?.length > 0 && <small className="evidence-columns">Columns: {item.columns.join(", ")}</small>}
          {opened[index] && <pre className="evidence-preview">{opened[index]}</pre>}
        </div>;
      })}
      {items.length > 5 && <button type="button" className="evidence-more" onClick={() => setShowAll(!showAll)}>
        {showAll ? "Show fewer sources" : `Show all ${items.length} sources`}
      </button>}
    </div>
  );
}
