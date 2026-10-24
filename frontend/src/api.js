import { requestSession, CLOUD_MODE } from "./cloud";
import { notifyAccessFailure } from "./access";
import { trackActivity } from "./activity";

if (CLOUD_MODE && !import.meta.env.VITE_API_BASE_URL?.startsWith("https://"))
  throw new Error("Cloud mode requires an HTTPS VITE_API_BASE_URL");

export const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");
async function request(path, { timeout = 125000, accessSession, ...options } = {}) {
  try {
    const session = accessSession === undefined ? await requestSession() : accessSession;
    const auth = session ? { Authorization: `Bearer ${session.access_token}` } : {};
    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      signal: AbortSignal.timeout(timeout),
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
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
      error.code = data.code;
      notifyAccessFailure(error, session);
      throw error;
    }
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

export function api(path, { silent = false, ...options } = {}) {
  return trackActivity(async () => {
    const response = await request(path, options);
    return response.json().catch(() => ({}));
  }, silent);
}

export async function uploadFile(caseId, kind, file) {
  const body = new FormData();
  body.append("file", file);
  return api(`/cases/${caseId}/files/${kind}`, { method: "POST", body });
}

export function downloadReport(caseId) {
  return trackActivity(() => saveReport(caseId));
}

async function saveReport(caseId) {
  const response = await request(`/cases/${caseId}/report`);
  const blob = await response.blob();
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
    const url = URL.createObjectURL(await response.blob());
    if (tab) tab.location.href = `${url}#page=${page}`;
    else window.open(`${url}#page=${page}`, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(url), 120000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}
