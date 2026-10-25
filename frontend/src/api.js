import { requestSession, CLOUD_MODE, CLOUD_PROVIDER } from "./cloud";
import { notifyAccessFailure } from "./access";
import { trackActivity } from "./activity";

if (CLOUD_MODE && !import.meta.env.VITE_API_BASE_URL?.startsWith("https://"))
  throw new Error("Cloud mode requires an HTTPS VITE_API_BASE_URL");

export const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");
const requestAccounts = new WeakMap();
const accountIdentity = session => session?.user
  ? `${session.user.id}:${session.user.email?.trim().toLowerCase()}` : null;

async function ensureAccount(origin) {
  if (CLOUD_MODE && accountIdentity(await requestSession()) !== accountIdentity(origin))
    throw new Error("Account changed. The previous operation remains with its account.");
}
async function request(path, { timeout = 125000, accessSession, ...options } = {}) {
  try {
    const session = accessSession === undefined ? await requestSession() : accessSession;
    const auth = session ? { Authorization: `Bearer ${session.identity_token || session.access_token}` } : {};
    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      signal: AbortSignal.timeout(timeout),
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
        ...(CLOUD_PROVIDER === "aws" && options.method && options.method !== "GET"
          ? { "Idempotency-Key": options.headers?.["Idempotency-Key"] || crypto.randomUUID() } : {}),
        ...auth,
      },
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(
        typeof data.detail === "string"
          ? data.detail
          : `The request could not be completed (${response.status}).`,
      );
      error.status = response.status;
      error.code = data.code || (CLOUD_PROVIDER === "aws" && response.status === 401 ? "session_invalid" : undefined);
      notifyAccessFailure(error, session);
      throw error;
    }
    await ensureAccount(session);
    requestAccounts.set(response, session);
    return response;
  } catch (error) {
    if (error.name === "TimeoutError")
      throw new Error("This request took too long. Please try again.");
    if (error instanceof TypeError)
      throw new Error(
        CLOUD_MODE
          ? "Could not connect to the cloud API. Please retry; if it persists, contact the app owner."
          : "Unable to reach the backend. Start the Sentinel backend and try again.",
      );
    throw error;
  }
}

export function api(path, { silent = false, jobOptions, ...options } = {}) {
  return trackActivity(async () => {
    const response = await request(path, options);
    const data = await response.json().catch(() => ({}));
    await ensureAccount(requestAccounts.get(response));
    if (response.status === 202 && data.job_id) return awaitJob(data.job_id, requestAccounts.get(response), jobOptions);
    return data;
  }, silent);
}

async function awaitJob(jobId, origin, { waitMs = 10 * 60 * 1000, deadlineAt, onProgress, returnPending = false } = {}) {
  const deadline = deadlineAt || Date.now() + waitMs;
  while (Date.now() < deadline) {
    await ensureAccount(origin);
    let job;
    try {
      job = await (await request(`/jobs/${jobId}`, { timeout: Math.max(1,Math.min(15000,deadline-Date.now())) })).json();
    } catch (error) {
      if (returnPending && ((!error.code && !error.status) || error.status >= 500)) {
        await ensureAccount(origin);
        return { pending:true, job_id:jobId, message:"Could not check validation. Check status to reconnect." };
      }
      throw error;
    }
    await ensureAccount(origin);
    if (job.status === "completed") return job.result_json || {};
    if (job.status === "failed") {
      const error=new Error(job.error || "Processing failed. Please retry.");
      error.code=job.error_code;
      throw error;
    }
    onProgress?.({stage:job.status === "running" ? "validating" : "queued",job_id:jobId});
    await new Promise(resolve => setTimeout(resolve, Math.max(0,Math.min(1500,deadline-Date.now()))));
  }
  if (returnPending) return {pending:true,job_id:jobId,message:"Validation is continuing in the background. You can leave and check status later."};
  throw new Error("Processing is continuing. You can check the case again shortly.");
}

export function cancelUpload(caseId, uploadId) {
  return api(`/cases/${caseId}/uploads/${uploadId}`,{method:"DELETE",timeout:10000,silent:true});
}

export async function checkUpload(jobId, onProgress) {
  return trackActivity(async()=>awaitJob(jobId,await requestSession(),{waitMs:120000,onProgress,returnPending:true}));
}

export async function uploadFile(caseId, kind, file, onProgress) {
  const extension=file.name.split(".").pop().toLowerCase();
  const allowed=kind === "contract" ? ["pdf","txt"] : ["csv"];
  if (!file.size || file.size>10*1024*1024) throw new Error("Choose a nonempty file up to 10 MiB.");
  if (!allowed.includes(extension)) throw new Error(`Choose a ${allowed.join(" or ").toUpperCase()} file for this section.`);
  if (CLOUD_PROVIDER === "aws") return trackActivity(async () => {
    const origin = await requestSession();
    onProgress?.({stage:"uploading"});
    const ticket = await api(`/cases/${caseId}/uploads/${kind}`, { method:"POST",timeout:15000,accessSession:origin, body:JSON.stringify({filename:file.name,size:file.size}) });
    const endpoint = new URL(ticket.url);
    if (endpoint.protocol !== "https:" || !endpoint.hostname.endsWith(".amazonaws.com")) throw new Error("Private upload destination is invalid");
    const form = new FormData();
    Object.entries(ticket.fields).forEach(([key,value]) => form.append(key,value));
    form.append("file",file);
    await ensureAccount(origin);
    try {
      const response = await fetch(ticket.url,{method:"POST",body:form,signal:AbortSignal.timeout(120000)});
      if (!response.ok) throw new Error("Upload did not finish. Please choose the file again.");
    } catch (error) {
      await ensureAccount(origin);
      await cancelUpload(caseId,ticket.upload_id).catch(()=>{});
      throw new Error(error.name === "TimeoutError" ? "File transfer timed out. Please choose the file again." : "File transfer failed. Check your connection and choose the file again.");
    }
    await ensureAccount(origin);
    onProgress?.({stage:"queued",upload_id:ticket.upload_id});
    return api(`/cases/${caseId}/uploads/${ticket.upload_id}/confirm`,{method:"POST",timeout:15000,accessSession:origin,
      jobOptions:{deadlineAt:Date.now()+120000,onProgress,returnPending:true}});
  });
  const body = new FormData();
  body.append("file", file);
  return api(`/cases/${caseId}/files/${kind}`, { method: "POST", body });
}

export function downloadReport(caseId) {
  return trackActivity(() => saveReport(caseId));
}

async function saveReport(caseId) {
  if (CLOUD_PROVIDER === "aws") {
    const origin = await requestSession();
    let result = await api(`/cases/${caseId}/report`);
    if (!result.url) result = await api(`/cases/${caseId}/report`);
    if (!result.url) throw new Error("Report is still preparing. Please retry.");
    const response = await fetch(result.url,{signal:AbortSignal.timeout(30000)});
    if (!response.ok) throw new Error("Report download failed. Please retry.");
    const blob = await response.blob();
    await ensureAccount(origin);
    return saveBlob(blob,caseId);
  }
  const response = await request(`/cases/${caseId}/report`);
  return saveBlob(await response.blob(),caseId);
}

function saveBlob(blob,caseId) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `sentinel-review-${caseId.slice(0, 8)}.pdf`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function openContractPdf(caseId, page) {
  return trackActivity(() => previewContract(caseId, page));
}

async function previewContract(caseId, page) {
  const tab = window.open("", "_blank");
  if (tab) tab.opener = null;
  try {
    const response = await request(`/cases/${caseId}/files/contract/original`);
    if (CLOUD_PROVIDER === "aws") {
      const { url } = await response.json();
      await ensureAccount(requestAccounts.get(response));
      if (tab) tab.location.href = `${url}#page=${page}`;
      else window.open(`${url}#page=${page}`,"_blank","noopener,noreferrer");
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    if (tab) tab.location.href = `${url}#page=${page}`;
    else window.open(`${url}#page=${page}`, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(url), 120000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}
