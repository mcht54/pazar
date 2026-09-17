import type {
  AnalysisJob,
  Business,
  BusinessDetail,
  DiscoveryJob,
  Region,
  Sector,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `İstek başarısız (${res.status})`);
  }
  return res.json();
}

export const api = {
  getRegions: () => request<Region[]>("/api/regions"),
  getSectors: () => request<Sector[]>("/api/sectors"),

  createDiscoveryJob: (region_id: number, sector_id: number, target_count: number) =>
    request<DiscoveryJob>("/api/discovery/jobs", {
      method: "POST",
      body: JSON.stringify({ region_id, sector_id, target_count }),
    }),
  getDiscoveryJob: (id: number) => request<DiscoveryJob>(`/api/discovery/jobs/${id}`),

  getBusinesses: (params: { region_id?: number; sector_id?: number }) => {
    const qs = new URLSearchParams();
    if (params.region_id) qs.set("region_id", String(params.region_id));
    if (params.sector_id) qs.set("sector_id", String(params.sector_id));
    return request<Business[]>(`/api/businesses?${qs.toString()}`);
  },
  getBusinessDetail: (id: number) => request<BusinessDetail>(`/api/businesses/${id}`),

  analyzeBusiness: (id: number) => request<AnalysisJob>(`/api/businesses/${id}/analyze`, { method: "POST" }),
  analyzeBulk: (payload: { business_ids?: number[]; top_n?: number }) =>
    request<AnalysisJob[]>("/api/businesses/analyze-bulk", { method: "POST", body: JSON.stringify(payload) }),
  getAnalysisJob: (id: number) => request<AnalysisJob>(`/api/analysis-jobs/${id}`),
};
