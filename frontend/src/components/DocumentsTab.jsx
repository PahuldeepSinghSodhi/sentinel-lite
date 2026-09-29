import { useState } from "react";
import { CheckCircle2, FileText, Loader2, Plus, Table2, UploadCloud } from "lucide-react";
import { api, uploadFile } from "../api";

const slots = [
  { kind: "transactions", title: "Transactions", description: "The charges you want to review.",
    format: "CSV · required", accept: ".csv", icon: Table2 },
  { kind: "contract", title: "Vendor contract", description: "Optional agreement for document questions.",
    format: "Text-based PDF or TXT · optional", accept: ".pdf,.txt", icon: FileText },
  { kind: "rate_card", title: "Approved rate card", description: "The rates used to check vendor charges.",
    format: "CSV · required", accept: ".csv", icon: Table2 },
];

export default function DocumentsTab({ review, onChange, onStart, onNewCase, busy }) {
  const [uploading, setUploading] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  async function handleFile(kind, file) {
    if (!file || !review) return;
    setUploading(kind);
    setError("");
    try {
      await uploadFile(review.id, kind, file);
      await onChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading("");
    }
  }
  async function startReview() {
    setStarting(true);
    setError("");
    try {
      await api(`/cases/${review.id}/start`, { method: "POST" });
      await onChange();
      onStart();
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }
  if (!review) return (
    <section className="panel gated-panel"><UploadCloud size={35} /><h2>Create a review case</h2>
      <p>Create a case to upload your own transactions and approved rate card, or Try sample to explore the demo.</p>
      <button className="button primary" onClick={onNewCase} disabled={busy}><Plus size={16} /> Add your files</button></section>
  );
  return (
    <div className="documents-layout">
      <section className="panel upload-panel">
        <div className="library-header"><div><p className="eyebrow">CASE FILES</p><h2>{review.ready ? "Source files" : "Add your files"}</h2>
          <p>{review.ready ? "These are the files used for this review." : "Choose your own files below. Each review keeps its files and history separate."}</p></div>
          {review.ready && <button className="button primary" onClick={onNewCase} disabled={busy}>
            <Plus size={15} /> Add your own files</button>}</div>
        {review.ready && <div className="upload-locked-note"><strong>Need to upload different files?</strong>
          <span>This review’s evidence is locked after Start review. Create a new case to add your own files; this case remains available in the case selector.</span></div>}
        {error && <div className="notice error" role="alert">{error}</div>}
        <div className="upload-grid">
          {slots.map(({ kind, title, description, format, accept, icon: Icon }) => {
            const file = review.files[kind];
            return <section className={`upload-slot ${file ? "filled" : ""}`} key={kind}>
              <span className="upload-icon"><Icon size={22} /></span>
              <div className="upload-slot-copy"><h3>{title}</h3><p>{description}</p><small>{format}</small></div>
              {file ? <div className="uploaded-file"><CheckCircle2 size={17} />
                <span><strong>{file.filename}</strong><small>{Math.max(1, Math.round(file.size / 1024))} KB uploaded</small></span></div>
                : <div className="upload-placeholder">No file uploaded</div>}
              {review.status === "draft" && <label className={`button secondary upload-action ${uploading || starting ? "disabled" : ""}`}>
                {uploading === kind ? <Loader2 className="spin" size={15} /> : <UploadCloud size={15} />}
                {uploading === kind ? "Uploading…" : file ? "Replace file" : `Add ${title.toLowerCase()}`}
                <input type="file" accept={accept} disabled={Boolean(uploading) || starting}
                  onChange={(event) => { handleFile(kind, event.target.files?.[0]); event.target.value = ""; }} />
              </label>}
            </section>;
          })}
        </div>
        <div className="upload-footer">
          <div><strong>{review.ready ? "Review active" : review.can_start ? "Ready to start" : "Two files required"}</strong>
            <p>{review.ready ? "Files are locked so past findings keep their original evidence. Create a new case for new files."
              : "Transactions and approved rate card are required before scanning or asking questions."}</p></div>
          {review.status === "draft" && <button className="button primary" disabled={!review.can_start || Boolean(uploading) || starting}
            onClick={startReview}>{starting ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
            {starting ? "Indexing files…" : "Start review"}</button>}
        </div>
      </section>
      <aside className="context-rail"><div className="context-card"><span className="rail-icon"><FileText size={23} /></span>
        <p className="eyebrow">SOURCE LOCATIONS</p><h2>Evidence you can inspect.</h2>
        <p>Findings and answers identify the original CSV row, TXT lines, or PDF page.</p>
        <div className="context-divider" /><strong>PDF support</strong>
        <p>PDFs must contain selectable text. Scanned images need OCR and are not supported in this version.</p>
      </div></aside>
    </div>
  );
}
