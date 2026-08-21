const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
export { API_BASE };

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function apiPost<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const fetcher = <T,>(path: string) => apiGet<T>(path);
export const poster = <T,>(path: string) => apiPost<T>(path);

export function outlookPath(index: string) {
  return `/outlook/${index}`;
}
export const indicesPath = "/indices";

export const trackingTodayPath = (index: string) => `/tracking/${index}/today`;
export const trackingPaperTradesPath = (index: string) => `/tracking/${index}/paper-trades`;
export const trackingNotExecutedPath = (index: string) => `/tracking/${index}/not-executed`;
export const invalidatedPath = (index: string) => `/tracking/${index}/invalidated`;
export const trackingHistoryPath = (index: string) => `/tracking/${index}/history`;
export const performancePath = "/performance";
export const generateNowPath = (index: string) => `/tracking/${index}/generate-now`;
export const checkNowPath = (index: string) => `/tracking/${index}/check-now`;
export const finalizeNowPath = (index: string) => `/tracking/${index}/finalize-now`;

export const equityCurvePath = (index: string) => `/performance/${index}/equity-curve`;
export const equityCurveAllPath = "/performance-equity-curve";

export const exportCsvUrl = (index: string) => `${API_BASE}/export/${index}/csv`;
export const exportXlsxUrl = (index: string) => `${API_BASE}/export/${index}/xlsx`;
export const exportAllCsvUrl = `${API_BASE}/export-all/csv`;
export const exportAllXlsxUrl = `${API_BASE}/export-all/xlsx`;
export const exportTodayXlsxUrl = `${API_BASE}/export-today/xlsx`;
export const yesterdayPath = (index: string) => `/tracking/${index}/yesterday`;
