import { useState } from "react";
import { CheckCircle2, FileText, Loader2, Plus, Table2, UploadCloud } from "lucide-react";
import { api, uploadFile, checkUpload, cancelUpload } from "../api";
import { CLOUD_MODE } from "../cloud";

const slots = [
  { kind: "transactions", title: "Transactions", description: "The charges you want to review.",
    format: "CSV · required", accept: ".csv", icon: Table2 },
  { kind: "contract", title: "Vendor contract", description: "Optional agreement for document questions.",
    format: "Text-based PDF or TXT · optional", accept: ".pdf,.txt", icon: FileText },
  { kind: "rate_card", title: "Approved rate card", description: "The rates used to check vendor charges.",
    format: "CSV · required", accept: ".csv", icon: Table2 },
];

const progressLabels = {uploading:"Uploading file…",queued:"Waiting for validation…",validating:"Checking file…"};

export default function DocumentsTab({ review, onChange, onStart, onNewCase, onTrySample, busy }) {
  const [uploading, setUploading] = useState("");
  const [progress, setProgress] = useState("uploading");
  const [pending, setPending] = useState({});
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  async function refreshAfterUpload(accepted) {
    try { await onChange(); if (accepted) setError(""); }
    catch { if (accepted) setError("Your file was accepted, but the displayed case could not refresh. Check status to refresh the case."); }
  }
  function remember(kind, result) {
    setPending(previous => ({...previous,[kind]:result?.pending ? result : null}));
  }
  async function handleFile(kind, file) {
    if (!file || !review) return;
    setUploading(kind);
    setError("");
    let accepted=false;
    try {
      const old=review.uploads?.[kind];
      if (old?.status === "reserved") await cancelUpload(review.id,old.id);
      const result=await uploadFile(review.id, kind, file, update=>setProgress(update.stage));
      remember(kind,result);
      accepted=!result?.pending;
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading("");
    }
    await refreshAfterUpload(accepted);
  }
  async function checkStatus(kind) {
    const jobId=pending[kind]?.job_id || review.uploads?.[kind]?.job_id;
    if (!jobId) { await refreshAfterUpload(false); return; }
    setUploading(kind); setProgress("queued"); setError("");
    let accepted=false;
    try {
      const result=await checkUpload(jobId,update=>setProgress(update.stage));
      remember(kind,result);accepted=!result?.pending;
    } catch(err) { remember(kind,null);setError(err.message); }
    finally {setUploading("");}
    await refreshAfterUpload(accepted);
  }
  async function startReview() {
    setStarting(true);
    setError("");
    try {
      await api(`/cases/${review.id}/start`, { method: "POST" });
      await onChange();
      if (!CLOUD_MODE) onStart();
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
        <div className="library-header"><div><p className="eyebrow">CASE FILES</p><h2>{review.ready ? "Source files" : review.is_sample ? "Sample source files" : "Add your files"}</h2>
          <p>{review.is_sample ? "Your private sample includes transactions, a vendor contract and approved rates." : review.ready ? "These are the files used for this review." : "Choose your own files below. Each review keeps its files and history separate."}</p></div>
          {review.ready && <button className="button primary" onClick={onNewCase} disabled={busy}>
            <Plus size={15} /> Add your own files</button>}</div>
        {review.ready && <div className="upload-locked-note"><strong>Need to upload different files?</strong>
          <span>This review’s evidence is locked after Start review. Create a new case to add your own files; this case remains available in the case selector.</span></div>}
        {review.is_sample && !review.ready && <div className="notice" role="status">
          {review.job?.status === "failed" ? <><strong>Sample preparation did not finish.</strong><p>{review.job.error || "Please retry the sample."}</p>
            <button className="button secondary" onClick={onTrySample} disabled={busy}>Retry sample</button></>
            : <><strong>Preparing sample…</strong><p>We’re preparing your private transactions, vendor contract and approved rate card. You can return to this case when it is ready.</p></>}
        </div>}
        {error && <div className="notice error" role="alert">{error}</div>}
        {error.includes("displayed case could not refresh") && <button className="button secondary" onClick={()=>refreshAfterUpload(true)}>Check status</button>}
        <div className="upload-grid">
          {slots.map(({ kind, title, description, format, accept, icon: Icon }) => {
            const file = review.files[kind];
            const upload = review.uploads?.[kind];
            const waiting = upload?.status === "queued" || Boolean(pending[kind]);
            const editable = review.status === "draft" && !review.is_sample;
            return <section className={`upload-slot ${file ? "filled" : ""}`} key={kind}>
              <span className="upload-icon"><Icon size={22} /></span>
              <div className="upload-slot-copy"><h3>{title}</h3><p>{description}</p><small>{format}</small>
                {kind !== "contract" && <small>Required columns: vendor_name, role_level, {kind === "transactions" ? "hourly_rate" : "approved_rate"}.</small>}</div>
              {file ? <div className="uploaded-file"><CheckCircle2 size={17} />
                <span><strong>{file.filename}</strong><small>{Math.max(1, Math.round(file.size / 1024))} KB uploaded</small></span></div>
                : <div className="upload-placeholder">No file uploaded</div>}
              {uploading === kind && <p role="status">{progressLabels[progress]}</p>}
              {waiting && uploading !== kind && <div role="status"><p>{pending[kind]?.message || "File validation is pending. Check status to continue."}</p>
                <button className="button secondary" onClick={()=>checkStatus(kind)} disabled={Boolean(uploading)}>Check status</button></div>}
              {upload?.status === "failed" && uploading !== kind && !pending[kind] && <p role="alert">{upload.error || "File was not accepted. Choose a file to retry."}</p>}
              {upload?.status === "reserved" && uploading !== kind && <p>Previous transfer did not finish. Choose a file to retry.</p>}
              {editable && <label className={`button secondary upload-action ${uploading || starting || waiting ? "disabled" : ""}`}>
                {uploading === kind ? <Loader2 className="spin" size={15} /> : <UploadCloud size={15} />}
                {uploading === kind ? progressLabels[progress] : file ? "Replace file" : `Add ${title.toLowerCase()}`}
                <input type="file" aria-label={`Upload ${title.toLowerCase()}`} accept={accept} disabled={Boolean(uploading) || starting || waiting}
                  onChange={(event) => { handleFile(kind, event.target.files?.[0]); event.target.value = ""; }} />
              </label>}
            </section>;
          })}
        </div>
        <div className="upload-footer">
          <div><strong>{review.ready ? "Review active" : review.is_sample ? (review.job?.status === "failed" ? "Sample needs attention" : "Preparing sample") : review.status === "starting" ? "Preparing review" : review.can_start ? "Ready to start" : "Two files required"}</strong>
            <p>{review.is_sample && !review.ready ? "Your sample files are provided automatically. Retry sample if preparation fails."
              : review.status === "starting" ? "Indexing is running in the background. This case will open automatically when ready."
              : review.ready ? "Files are locked so past findings keep their original evidence. Create a new case for new files."
              : "Transactions and approved rate card are required before scanning or asking questions."}</p></div>
          {review.status === "draft" && !review.is_sample && <button className="button primary" disabled={!review.can_start || Boolean(uploading) || starting}
            onClick={startReview}>{starting ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
            {starting ? "Preparing…" : "Start review"}</button>}
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
