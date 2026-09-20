import type {
  ActivityList,
  FollowUpItem,
  CallToday,
  CrmSalesFields,
  EmailState,
  FollowUps,
  Funnel,
  Revenue,
  SalesOverview,
  SalesPlan,
  SalesSuggestions,
  ServicePriceRow,
  StaffPerformance,
  AdminUsers,
  AuthUser,
  GoogleApiState,
  StaffReport,
  AnalysisJob,
  Business,
  BusinessDetail,
  AnalysisReport,
  AnalyzedList,
  CrmEntry,
  CrmList,
  CrmState,
  CrmSummary,
  ReportPeriod,
  DiscoveryJob,
  Guide,
  GuideSummary,
  Region,
  SalesNote,
  Sector,
} from "./types";

/**
 * API adresi. NEXT_PUBLIC_* değerleri `next build` sırasında pakete GÖMÜLÜR; çalışma anında değiştirilemez.
 * - Üretim (varsayılan): "" → aynı köken. Tarayıcı `/api/...` yoluna gider; Nginx `/api`'yi API'ye yönlendirir
 *   (Nginx yoksa next.config.mjs'deki `/api` rewrite'ı aynı işi yapar). Böylece çerez aynı kökende kalır, CORS gerekmez.
 * - Geliştirme (`next dev`): API ayrı portta (localhost:8000) çalışır.
 * - Ayrı bir API alan adı gerekiyorsa build sırasında NEXT_PUBLIC_API_BASE_URL verilir (örn. https://api.example.com).
 */
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "")).replace(/\/+$/, "");

/** Oturum denetimi gibi arayüzü bloke eden istekler yanıtsız kalırsa sonsuza dek beklenmez. */
const AUTH_TIMEOUT_MS = 10_000;

/** Oturum çerezi (HttpOnly) her istekte gönderilir; değiştirici isteklerde CSRF başlığı zorunludur. */
const COMMON_HEADERS = { "X-Requested-With": "mch-app" };

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function notifyAuth(res: Response) {
  if (typeof window === "undefined") return;
  if (res.status === 401) window.dispatchEvent(new Event("mch:unauthorized"));
  if (res.status === 403 && res.headers.get("X-Auth") === "password-change") window.dispatchEvent(new Event("mch:password-change"));
}

async function request<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs, ...fetchInit } = init ?? {};
  const controller = timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...fetchInit,
      signal: controller?.signal,
      cache: "no-store",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...COMMON_HEADERS, ...(fetchInit.headers ?? {}) },
    });
  } catch {
    throw new ApiError(controller?.signal.aborted ? "Sunucu zamanında yanıt vermedi. Lütfen tekrar deneyin." : "Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.", 0);
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (!res.ok) {
    notifyAuth(res);
    const body = await res.json().catch(() => ({}));
    throw new ApiError(typeof body.detail === "string" ? body.detail : `İstek başarısız oldu (${res.status})`, res.status);
  }
  return res.json();
}

export interface HealthStatus {
  status: string;
  env: string;
  discovery_provider: "google_maps" | "google" | "mock" | string;
  google_places_configured: boolean;
  is_real_data_source: boolean;
}

async function download(path: string, body: unknown, fallbackName: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...COMMON_HEADERS }, body: JSON.stringify(body) });
  } catch {
    throw new Error("Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.");
  }
  if (!res.ok) {
    notifyAuth(res);
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : `Dışa aktarma başarısız oldu (${res.status})`);
  }
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  getHealth: () => request<HealthStatus>("/api/health"),
  getRegions: () => request<Region[]>("/api/regions"),
  getSectors: () => request<Sector[]>("/api/sectors"),

  createDiscoveryJob: (region_id: number, sector_id: number, target_count: number) =>
    request<DiscoveryJob>("/api/discovery/jobs", {
      method: "POST",
      body: JSON.stringify({ region_id, sector_id, target_count, auto_analyze: true }),
    }),
  getDiscoveryJob: (id: number) => request<DiscoveryJob>(`/api/discovery/jobs/${id}`),

  getBusinesses: (params: { job_id?: number; region_id?: number; sector_id?: number }) => {
    const qs = new URLSearchParams();
    if (params.job_id) qs.set("job_id", String(params.job_id));
    if (params.region_id) qs.set("region_id", String(params.region_id));
    if (params.sector_id) qs.set("sector_id", String(params.sector_id));
    return request<Business[]>(`/api/businesses?${qs.toString()}`);
  },
  getBusinessDetail: (id: number) => request<BusinessDetail>(`/api/businesses/${id}`),

  analyzeBusiness: (id: number) => request<AnalysisJob>(`/api/businesses/${id}/analyze`, { method: "POST" }),
  analyzeBulk: (payload: { business_ids?: number[]; top_n?: number }) =>
    request<AnalysisJob[]>("/api/businesses/analyze-bulk", { method: "POST", body: JSON.stringify(payload) }),
  getAnalysisJob: (id: number) => request<AnalysisJob>(`/api/analysis-jobs/${id}`),

  // --- satış paneli / CRM / rehber / dışa aktarma
  getToday: (limit = 10) => request<Business[]>(`/api/dashboard/today?limit=${limit}`),
  addToCrm: (id: number, body: { stage: string; note?: string } & CrmSalesFields) =>
    request<CrmState>(`/api/businesses/${id}/crm`, { method: "POST", body: JSON.stringify(body) }),
  updateCrm: (id: number, body: { stage?: string; staff_note?: string } & CrmSalesFields) =>
    request<CrmState>(`/api/businesses/${id}/crm`, { method: "PATCH", body: JSON.stringify(body) }),
  getCrmList: (params: Record<string, string | number | null | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
    return request<CrmList>(`/api/crm?${qs.toString()}`);
  },
  getCrmServices: () => request<string[]>("/api/crm/services"),
  createFollowUp: (body: { business_id: number; due_at: string; note?: string | null; user_id?: number | null }) =>
    request<FollowUpItem>("/api/follow-ups", { method: "POST", body: JSON.stringify(body) }),
  patchFollowUp: (id: number, body: { due_at?: string; note?: string | null; user_id?: number | null; status?: string }) =>
    request<FollowUpItem>(`/api/follow-ups/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  completeFollowUpById: (id: number, body: { result: string; note?: string; next_follow_up_at?: string | null }) =>
    request<FollowUpItem>(`/api/follow-ups/${id}/complete`, { method: "POST", body: JSON.stringify(body) }),
  logContact: (id: number, body: { channel: string; result: string; note?: string }) =>
    request<CrmState>(`/api/crm/${id}/contact`, { method: "POST", body: JSON.stringify(body) }),
  getCrmOwners: () => request<{ id: number; name: string }[]>("/api/crm/owners"),
  getFollowUps: (scope: "mine" | "all" = "mine") => request<FollowUps>(`/api/crm/follow-ups?scope=${scope}`),
  completeFollowUp: (id: number, body: { result: string; note?: string; next_follow_up_at?: string | null }) =>
    request<CrmState>(`/api/crm/${id}/follow-up/complete`, { method: "POST", body: JSON.stringify(body) }),
  getCallToday: (scope: "mine" | "all" = "mine", limit = 10) => request<CallToday>(`/api/sales/call-today?scope=${scope}&limit=${limit}`),
  getSalesPlan: (id: number) => request<SalesPlan>(`/api/sales/plan/${id}`),
  getFunnel: (period: string) => request<Funnel>(`/api/sales/funnel?period=${period}`),
  getRevenue: (by: "service" | "sector", period: string) => request<Revenue>(`/api/sales/revenue?by=${by}&period=${period}`),
  getSalesSuggestions: () => request<SalesSuggestions>("/api/sales/suggestions"),
  getStaffPerformance: (period: string) => request<StaffPerformance>(`/api/sales/staff?period=${period}`),
  getSalesOverview: (period: string) => request<SalesOverview>(`/api/sales/report?period=${period}`),
  getCrmSummary: () => request<CrmSummary>("/api/crm/summary"),
  getAnalysisReport: () => request<AnalysisReport>("/api/reports/analysis"),
  getAnalyzedBusinesses: (period: ReportPeriod) => request<AnalyzedList>(`/api/reports/analysis/businesses?period=${period}`),
  getSalesNote: (id: number) => request<SalesNote>(`/api/businesses/${id}/sales-note`),
  listGuides: () => request<{ categories: string[]; guides: GuideSummary[] }>("/api/guides"),
  getGuide: (id: string, params: { business_id?: number; sector_id?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.business_id) qs.set("business_id", String(params.business_id));
    if (params.sector_id) qs.set("sector_id", String(params.sector_id));
    return request<Guide>(`/api/guides/${id}?${qs.toString()}`);
  },
  // --- kimlik doğrulama
  login: (identifier: string, password: string, remember = false) => request<AuthUser>("/api/auth/login", { method: "POST", body: JSON.stringify({ identifier, password, remember }), timeoutMs: 30_000 }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => request<AuthUser>("/api/auth/me", { timeoutMs: AUTH_TIMEOUT_MS }),
  changePassword: (current_password: string, new_password: string) =>
    request<AuthUser>("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),

  // --- yönetim (yalnızca yönetici)
  listUsers: () => request<AdminUsers>("/api/admin/users"),
  createUser: (body: { name: string; email: string; username: string; role: string; password?: string; is_active: boolean; send_invite?: boolean }) =>
    request<AuthUser & { temporary_password?: string; invite_sent?: boolean; invite_error?: string }>("/api/admin/users", { method: "POST", body: JSON.stringify(body) }),
  sendPasswordLink: (id: number) => request<{ ok: boolean; message: string }>(`/api/admin/users/${id}/send-link`, { method: "POST" }),
  forgotPassword: (email: string) => request<{ message: string }>("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  checkResetToken: (token: string) => request<{ valid: boolean; purpose?: string; name?: string | null; message?: string }>(`/api/auth/reset-token?token=${encodeURIComponent(token)}`),
  setPassword: (token: string, new_password: string) => request<{ ok: boolean; message: string }>("/api/auth/set-password", { method: "POST", body: JSON.stringify({ token, new_password }) }),
  getEmailSettings: () => request<EmailState>("/api/admin/email-settings"),
  saveEmailSettings: (body: { host: string; port: number; username: string | null; password: string | null; from_name: string; from_email: string; security: string }) =>
    request<EmailState>("/api/admin/email-settings", { method: "PUT", body: JSON.stringify(body) }),
  testEmailSettings: (to: string) => request<{ ok: boolean; message: string; state: EmailState }>("/api/admin/email-settings/test", { method: "POST", body: JSON.stringify({ to }) }),
  toggleEmailSettings: (enabled: boolean) => request<EmailState>("/api/admin/email-settings/enabled", { method: "PUT", body: JSON.stringify({ enabled }) }),
  getServicePrices: () => request<{ items: ServicePriceRow[]; not_priced_label: string; disclaimer: string }>("/api/admin/service-prices"),
  saveServicePrice: (id: number, body: { min_price: number | string | null; max_price: number | string | null; default_price: number | string | null; is_active: boolean }) =>
    request<ServicePriceRow>(`/api/admin/service-prices/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  updateUser: (id: number, body: Partial<{ name: string; email: string; username: string; role: string; is_active: boolean }>) =>
    request<AuthUser>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  resetPassword: (id: number, new_password?: string) =>
    request<{ temporary_password: string }>(`/api/admin/users/${id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: new_password || null }) }),
  getActivity: (params: Record<string, string | number | null | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
    return request<ActivityList>(`/api/admin/activity?${qs.toString()}`);
  },
  getStaffReport: (period: string) => request<StaffReport>(`/api/admin/reports/staff?period=${period}`),
  getGoogleApi: () => request<GoogleApiState>("/api/admin/api-settings/google"),
  saveGoogleKey: (api_key: string) => request<GoogleApiState>("/api/admin/api-settings/google/key", { method: "PUT", body: JSON.stringify({ api_key }) }),
  removeGoogleKey: () => request<GoogleApiState>("/api/admin/api-settings/google/key", { method: "DELETE" }),
  testGoogleApi: () => request<{ ok: boolean; message: string; state: GoogleApiState }>("/api/admin/api-settings/google/test", { method: "POST" }),
  toggleGoogleApi: (enabled: boolean) => request<GoogleApiState>("/api/admin/api-settings/google/enabled", { method: "PUT", body: JSON.stringify({ enabled }) }),

  exportBusinesses: (ids: number[], format: "csv" | "xlsx") => download("/api/businesses/export", { ids, format }, `isletmeler.${format}`),
};
