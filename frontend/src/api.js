import { authHeaders, CLOUD_MODE } from "./cloud";

if (CLOUD_MODE && !import.meta.env.VITE_API_BASE_URL?.startsWith("https://"))
  throw new Error("Cloud mode requires an HTTPS VITE_API_BASE_URL");

export const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");
export async function api(path, { timeout = 125000, ...options } = {}) {
  try {
    const auth = await authHeaders();
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
    const data = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : `The request could not be completed (${response.status}).`,
      );
    return data;
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

export async function uploadFile(caseId, kind, file) {
  const body = new FormData();
  body.append("file", file);
  return api(`/cases/${caseId}/files/${kind}`, { method: "POST", body });
}

export async function downloadReport(caseId) {
  const response = await fetch(`${BASE_URL}/cases/${caseId}/report`, { headers: await authHeaders() });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Could not download the report.");
  }
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

export async function openContractPdf(caseId, page) {
  const tab = window.open("", "_blank");
  if (tab) tab.opener = null;
  try {
    const response = await fetch(`${BASE_URL}/cases/${caseId}/files/contract/original`,
      { headers: await authHeaders() });
    if (!response.ok) throw new Error("Could not open the contract PDF.");
    const url = URL.createObjectURL(await response.blob());
    if (tab) tab.location.href = `${url}#page=${page}`;
    else window.open(`${url}#page=${page}`, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(url), 120000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}
