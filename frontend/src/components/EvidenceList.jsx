import { useState } from "react";
import { FileSearch, Loader2 } from "lucide-react";
import { api, BASE_URL } from "../api";

export default function EvidenceList({ caseId, items = [], title = "Supporting evidence", anchorPrefix }) {
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
      setOpened((previous) => ({ ...previous, [index]: data }));
    } catch (error) {
      setOpened((previous) => ({ ...previous, [index]: { text: `Could not open source: ${error.message}` } }));
    } finally {
      setLoading((previous) => ({ ...previous, [index]: false }));
    }
  }
  if (!items.length) return null;
  const visible = anchorPrefix || showAll ? items : items.slice(0, 5);
  return (
    <div className="evidence-list">
      <p className="evidence-title">{title} <span>({items.length})</span></p>
      {visible.map((item, index) => {
        const canOpen = Boolean(item.kind && (item.page || item.row_number || (item.line_start && item.line_end)));
        const pdfHref = item.kind === "contract" && item.page
          ? `${BASE_URL}/cases/${encodeURIComponent(caseId)}/files/contract/original#page=${item.page}` : null;
        return <div className="evidence-item" id={anchorPrefix ? `${anchorPrefix}-${item.id || index + 1}` : undefined}
          key={`${item.source}-${item.location}-${index}`}>
          {pdfHref ? <div className="evidence-link evidence-pdf">
            <FileSearch size={15} />
            <a href={pdfHref} target="_blank" rel="noopener noreferrer">
              {item.source} · {item.location || "Location unavailable"}</a>
            <button type="button" onClick={() => show(index, item)} aria-expanded={Boolean(opened[index])}>
              {loading[index] ? "Loading…" : opened[index] ? "Hide text" : "View extracted text"}</button>
          </div> : canOpen ? <button type="button" className="evidence-link" onClick={() => show(index, item)}
            aria-expanded={Boolean(opened[index])}>
            {loading[index] ? <Loader2 className="spin" size={15} /> : <FileSearch size={15} />}
            <span>{item.source} · {item.location || "Location unavailable"}</span>
            <small>{opened[index] ? "Hide" : "Open source"}</small>
          </button> : <div className="evidence-link evidence-unavailable">
            <FileSearch size={15} /><span>{item.source} · {item.location || "Location unavailable"}</span>
            <small>Preview unavailable</small></div>}
          {item.columns?.length > 0 && <small className="evidence-columns">Columns: {item.columns.join(", ")}</small>}
          {opened[index] && <div className="evidence-preview">
            {opened[index].values ? <dl className="evidence-csv">
              {Object.entries(opened[index].values).map(([column, value]) =>
                <div className={item.columns?.includes(column) ? "relevant" : ""} key={column}>
                  <dt>{column}</dt><dd>{String(value ?? "")}</dd>
                </div>)}
            </dl> : <pre>{opened[index].text}</pre>}
          </div>}
        </div>;
      })}
      {!anchorPrefix && items.length > 5 && <button type="button" className="evidence-more" onClick={() => setShowAll(!showAll)}>
        {showAll ? "Show fewer sources" : `Show all ${items.length} sources`}
      </button>}
    </div>
  );
}
