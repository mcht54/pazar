export interface Region {
  id: number;
  name: string;
  parent_region_id: number | null;
  level: "il" | "ilce";
  search_radius_m: number;
}

export interface Sector {
  id: number;
  name: string;
  group_name: string | null;
}

export interface DiscoveryJob {
  id: number;
  region_id: number;
  sector_id: number;
  target_count: number;
  status: "pending" | "running" | "completed" | "partial" | "failed";
  found_new: number;
  found_existing: number;
  item_errors: { external_ref: string; reason: string }[];
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  total_count: number;
  analyzed_count: number;
  analyzing_count: number;
  failed_analysis_count: number;
}

export type VerifyStatus = "dogrulandi" | "celiskili" | "bulunamadi" | "tek_kaynak";

export interface VerifiedField {
  key: string;
  label: string;
  value: string | null;
  status: VerifyStatus;
  sources: { key: string; label: string; value: string | null; url: string | null }[];
  note: string;
  checked: boolean; // false: değeri kontrol edecek yetkili kaynağa erişilemedi
}

export interface SourceStatusItem {
  key: string;
  label: string;
  status: "kontrol_edildi" | "erisilemedi" | "eslesme_yok" | "atlandi";
  detail: string;
  checked_at: string | null;
}

export interface SocialAccount {
  network: string;
  label: string;
  url: string | null;
  status: VerifyStatus;
  sources: string[];
  note: string;
}

export interface QuickRow {
  label: string;
  state: "VAR" | "YOK" | "ZAYIF" | "DOĞRULANAMADI";
  value: string;
}

export type SalesLevel = "Yüksek" | "Orta" | "Düşük" | "Belirsiz";

export interface Business {
  id: number;
  name: string;
  sector_id: number;
  sector_name: string;
  region_id: number;
  region_label: string;
  address: string | null;
  phone: string | null;
  website: string | null;
  email: string | null;
  lat: number | null;
  lng: number | null;
  google_rating: number | null;
  google_review_count: number | null;
  photo_count: number | null;
  opening_hours: string | null;
  category_label: string | null;
  maps_url: string | null;
  maps_search_url: string;
  last_review_at: string | null;
  discovery_source: string;
  source_label: string;
  source_url: string | null;
  source_checked_at: string | null;
  is_demo_data: boolean;
  status: "discovered" | "analyzing" | "analyzed" | "analysis_failed";
  crm_stage: string;
  last_analysis_at: string | null;
  sales_level: SalesLevel | null;
  sales_reason: string | null;
  needs_verification: boolean | null;
  primary_service: string | null;
  secondary_service: string | null;
  top_opportunity: string | null;
  gap_summary: string[];
  why_call: string | null;
  sales_note: string | null;
  gbp_summary: string | null;
  web_summary: string | null;
  verification: Record<string, VerifiedField>;
  source_statuses: SourceStatusItem[];
  social_accounts: SocialAccount[];
  web_quick: QuickRow[];
  gbp_quick: QuickRow[];
  talking_point: string | null;
  sales_score: number | null;
  score_band: string | null;
  top_problem: string | null;
  staff_note: string | null;
  crm_updated_at: string | null;
  in_crm: boolean; // CRM'de mi? (analiz firmayı CRM'e eklemez; CRM'e ekleme ayrı ve bilinçli bir işlemdir)
  crm_added_at: string | null;
  province_name: string | null;
  district_name: string | null;
  crm_added_by_name: string | null;
  // --- satış takibi (CRM)
  crm_owner_id?: number | null;
  crm_owner_name?: string | null;
  next_follow_up_at?: string | null;
  follow_up_note?: string | null;
  follow_up_state?: "overdue" | "today" | "upcoming" | null;
  last_contact_at?: string | null;
  interested_service?: string | null;
  offer_amount?: number | null;
  sale_amount?: number | null;
  lost_reason?: string | null;
  crm_updated_by_name: string | null;
  crm_last_action: string | null;
  analysis_state: "none" | "running" | "completed" | "partial" | "failed";
  analysis_state_label: string;
  last_analyzed_by_name: string | null;
  priority_score: number | null;
  priority_reasons: string[];
  why_prospect: string[];
  top_guide_id: string | null;
  prospect_kind: string | null; // 'rakip' | 'kamu' | 'kendi' → müşteri adayı değil (panelde listelenmez)
  prospect_label: string | null;
  prospect_reason: string | null;
  previously_analyzed: boolean; // bakan kullanıcı bunu bu aramadan önce KENDİSİ analiz etmiş mi
  analyzed_by_me: boolean;
  analyzed_by_me_at: string | null;
  analyzed_by_others: boolean; // sistemde analiz verisi var ama sizin analiziniz yok
}

export interface BusinessMetric {
  id: number;
  metric_key: string;
  value: { label?: string; value?: unknown; status?: string; detail?: string } | null;
  unit: string | null;
  status: "known" | "unknown" | "unverified" | "not_available";
  source: string;
  collected_at: string;
}

export interface Finding {
  id: number;
  category: string;
  finding: string;
  severity: "none" | "low" | "medium" | "high";
  evidence: string;
  source: string;
  confidence: "low" | "medium" | "high";
  detected_at: string;
  based_on_metric_ids: number[];
  business_impact: string | null;
  mchttasarim_opportunity: string | null;
  recommended_service_ids: number[];
}

export interface ServiceRecommendation {
  service_id: number;
  service_name: string;
  priority_rank: number;
  matched_rule: string;
  ai_justification: string | null;
}

export interface CompetitorMetricRow {
  metric_key: string;
  business_value: { value: unknown } | null;
  business_status: string;
  competitors: { competitor_id: number; competitor_name: string; value: { value: unknown } | null; status: string }[];
}

export interface AnalysisJob {
  id: number;
  business_id: number;
  status: "pending" | "running" | "completed" | "partial" | "failed";
  stages_status: Record<string, string>;
  started_at: string | null;
  completed_at: string | null;
}

export interface Check {
  key: string;
  area: "website" | "gbp" | "social";
  label: string;
  status: "ok" | "problem" | "unknown";
  value: string;
  detail: string;
  severity: "none" | "low" | "medium" | "high";
  confidence: "low" | "medium" | "high";
  why: string;
  services: string[];
  needs_verification: boolean;
  guide_id?: string | null;
}

export interface OpportunityProblem {
  label: string;
  evidence: string;
  severity: "none" | "low" | "medium" | "high";
  confidence: "low" | "medium" | "high";
  needs_verification: boolean;
  check_key: string;
  area: string;
  guide_id: string | null;
}

export interface Opportunity {
  service: string;
  level: "Yüksek" | "Orta" | "Düşük" | "Doğrulanmadı";
  verified: boolean;
  problems: OpportunityProblem[];
  problem_text?: string;
  why: string;
  rationale: string;
  offer: string;
  guide_id?: string | null;
  fallback_guide_id?: string | null;
}

export interface ScoreItem {
  kind: "tespit" | "varsayım";
  area?: string;
  area_label?: string;
  label: string;
  points: number;
  explanation: string;
  services?: string[];
}

export interface ScoreInfo {
  score: number;
  band: string;
  groups?: { label: string; points: number }[];
  items: ScoreItem[];
  adjustments: { label: string; points: number }[];
  assumptions: ScoreItem[];
  summary: string;
  note: string;
}

export interface CrmEntry {
  id?: number;
  user_id?: number | null;
  user_name?: string;
  type: "added" | "status_change" | "note" | string;
  from_stage: string | null;
  to_stage: string | null;
  note: string | null;
  created_at: string;
  meta?: Record<string, unknown> | null;
}

export interface GuideSummary {
  id: string;
  category: string;
  title: string;
  services: string[];
}

export interface Guide {
  id: string;
  category: string;
  title: string;
  services: string[];
  sections: {
    what: string;
    why: string;
    solution: string;
    steps: string[];
    pitch: string;
    offer: string;
    questions: string[];
    verify: string[];
  };
  business_evidence: { problem: string; evidence: string; why: string; severity: string; confidence: string }[];
}

export interface SalesNote {
  business: string;
  sector: string;
  place: string;
  level: string;
  phone: string | null;
  problems: { problem: string; evidence: string; verified: boolean }[];
  primary_service: string | null;
  secondary_service: string | null;
  why_service: string;
  pitch: string | null;
  talking_point: string | null;
  questions: string[];
  caveats: string[];
  text: string;
}

export interface Assessment {
  level: SalesLevel;
  level_reason: string;
  needs_verification: boolean;
  primary_service: string | null;
  secondary_service: string | null;
  top_opportunity: string | null;
  why_call: string | null;
  talking_point: string | null;
  sales_note: string | null;
  gaps: Check[];
  opportunities: { evidence: Opportunity[]; possible: Opportunity[] };
  score: ScoreInfo;
  service_matrix?: ServiceMatrix;
  priority?: PriorityInfo;
  why_prospect?: string[];
  strengths: { label: string; value: string }[];
  services: { service: string; is_primary: boolean; reasons: string[] }[];
  possible_services: { service: string; basis: string }[];
  verification_steps: string[];
  social?: Check[];
  website: {
    url?: string | null;
    analyzed?: boolean;
    status_text?: string;
    final_url?: string;
    http_status?: number;
    response_ms?: number;
    checked_at?: string;
    pagespeed?: { performance_score?: number } | null;
    pagespeed_note?: string | null;
    title?: string | null;
    meta_description?: string | null;
    checks: Check[];
  };
  gbp: {
    source?: string;
    source_label?: string;
    available?: boolean;
    checked_at?: string | null;
    maps_url?: string | null;
    maps_search_url?: string;
    status_text?: string;
    checks: Check[];
  };
  analyzed_at: string;
}

export interface BusinessDetail {
  business: Business;
  assessment: Assessment | null;
  metrics: BusinessMetric[];
  findings: Finding[];
  service_recommendations: ServiceRecommendation[];
  competitors: CompetitorMetricRow[];
  latest_analysis_job: AnalysisJob | null;
  crm_history: CrmEntry[];
  follow_ups: FollowUpItem[];
  analysis_history: AnalysisHistoryItem[];
}

export interface FollowUpItem {
  id: number;
  business_id: number;
  user_id: number | null;
  user_name: string | null;
  due_at: string;
  has_time: boolean;
  note: string | null;
  status: "Bekliyor" | "Tamamlandı" | "İptal";
  result: string | null;
  completed_at: string | null;
  date_state: "overdue" | "today" | "upcoming" | null;
  time_passed: boolean;
  business?: { id: number; name: string; phone: string | null; crm_stage: string; crm_owner_id: number | null };
}

export interface CrmState {
  follow_ups?: FollowUpItem[];
  in_crm: boolean;
  crm_stage: string;
  staff_note: string | null;
  crm_added_at: string | null;
  crm_updated_at: string | null;
  crm_added_by_name?: string | null;
  crm_updated_by_name?: string | null;
  crm_last_action?: string | null;
  crm_owner_id?: number | null;
  crm_owner_name?: string | null;
  next_follow_up_at?: string | null;
  follow_up_note?: string | null;
  follow_up_state?: "overdue" | "today" | "upcoming" | null;
  last_contact_at?: string | null;
  interested_service?: string | null;
  offer_amount?: number | null;
  sale_amount?: number | null;
  lost_reason?: string | null;
  history: CrmEntry[];
}

export interface CrmList {
  total: number;
  filtered_total: number;
  page: number;
  page_size: number;
  pages: number;
  counts: Record<string, number>;
  facets: {
    provinces: { id: number; name: string }[];
    districts: { id: number; name: string; province_id: number | null }[];
    sectors: { id: number; name: string }[];
    services: string[];
    users: { id: number; name: string }[];
  };
  items: Business[];
}

export interface CrmSummary {
  total: number;
  by_stage: Record<string, number>;
}

export interface PeriodStat {
  analyses: number; // başarıyla TAMAMLANAN analiz işlemi sayısı (aynı firmanın tekrar analizi ayrı sayılır)
  businesses: number; // aralıkta en az bir başarılı analizi olan BENZERSİZ firma sayısı
  since: string | null; // aralık başlangıcı (dahil), Europe/Istanbul
  until: string | null; // aralık bitişi (hariç)
}

export interface AnalysisReport {
  timezone: string;
  updated_at: string; // backend'in hesapladığı an (Europe/Istanbul)
  first_analysis_at: string | null; // sistemdeki ilk başarılı analiz kaydı
  today: PeriodStat;
  week: PeriodStat;
  month: PeriodStat;
  total: PeriodStat;
}

export type ReportPeriod = "today" | "week" | "month" | "total";

export interface AnalyzedList {
  period: ReportPeriod;
  label: string;
  analyses: number;
  businesses_count: number;
  items: Business[];
}

// ---------------------------------------------------------------- kimlik doğrulama / yönetim
export type Role = "yonetici" | "calisan" | "stajyer";

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  username: string | null;
  role: Role;
  role_label: string;
  role_icon: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  permissions: string[];
}

export interface AdminUsers {
  roles: { key: Role; label: string }[];
  items: AuthUser[];
}

export interface ActivityItem {
  id: number;
  created_at: string;
  user_id: number | null;
  user_name: string;
  action: string;
  action_label: string;
  business_id: number | null;
  business_name: string | null;
  detail: string | null;
}

export interface ActivityList {
  total: number;
  actions: { key: string; label: string }[];
  items: ActivityItem[];
}

export interface StaffReportRow {
  user_id: number;
  name: string;
  role: Role;
  is_active: boolean;
  analyses: number;
  searches: number;
  crm_added: number;
  calls: number;
  offers: number;
  customers: number;
  notes: number;
  status_changes: number;
  exports: number;
  logins: number;
}

export interface StaffReport {
  period: ReportPeriod;
  label: string;
  since: string | null;
  items: StaffReportRow[];
}

export interface GoogleApiState {
  status: "not_connected" | "saved" | "connected" | "active" | "error";
  status_icon: string;
  status_label: string;
  has_key: boolean;
  key_source: "panel" | "environment" | "none";
  masked_key: string | null;
  enabled: boolean;
  last_test_ok: boolean | null;
  last_test_at: string | null;
  last_test_message: string | null;
  updated_at: string | null;
  note: string;
}

// ---------------------------------------------------------------- hizmet matrisi / öncelik
export type MatrixLevel = "satis" | "olasi" | "zayif" | "uygun_degil";

export interface MatrixEvidence {
  text: string;
  detail: string;
  severity: string;
  confidence: string;
  verified: boolean;
  weight: number;
  check_key: string | null;
  area: string;
  guide_id: string | null;
  why: string;
}

export interface MatrixItem {
  service: string;
  level: MatrixLevel;
  level_label: string;
  verified: boolean;
  problem: string;
  evidence: MatrixEvidence[];
  why: string;
  what: string;
  pitch: string;
  caveat: string | null;
  not_applicable_reason: string | null;
  commercial: number;
  recurring: boolean;
  relevance: number;
  evidence_weight: number;
  sector_only: boolean;
  guide_id: string | null;
  primary?: boolean;
}

export interface ServiceMatrix {
  items: MatrixItem[];
  counts: Record<MatrixLevel, number>;
  top: string[];
}

export interface PriorityInfo {
  value: number;
  components: Record<string, number>;
  weights: Record<string, number>;
  reasons: string[];
}

export interface AnalysisHistoryItem {
  id: number;
  status: string;
  trigger: string;
  user_id: number | null;
  user_name: string;
  started_at: string | null;
  completed_at: string | null;
}


// ================================================================ satış operasyonu
export interface CrmSalesFields {
  follow_up_at?: string | null;
  follow_up_note?: string | null;
  offer_amount?: number | string | null;
  sale_amount?: number | string | null;
  lost_reason?: string | null;
  interested_service?: string | null;
  owner_id?: number | null;
}

export interface FollowUps {
  counts: { overdue: number; today: number; tomorrow: number; week: number; upcoming: number };
  overdue: Business[];
  today: Business[];
  tomorrow: Business[];
  week: Business[];
  upcoming: Business[];
  results: string[];
  updated_at: string;
}

export interface CallToday {
  items: { business: Business; call: { sources: { key: string; label: string }[]; score: number; reasons: string[]; components: Record<string, number>; weights: Record<string, number>; next_action: string } }[];
  total_candidates: number;
  eligible: number;
  excluded: Record<string, number>;
  scope: "mine" | "all";
  updated_at: string;
}

export interface PlanEvidence {
  text: string;
  detail: string;
  verified: boolean;
  severity: string;
  source_label: "Google" | "Website" | "Social" | "Çapraz kontrol" | "Doğrulanamadı";
  state: "dogrulandi" | "dogrulanmadi";
}
export interface Estimate { priced: boolean; min: number | null; max: number | null; default: number | null; label: string }
export interface PlanOpportunity {
  service: string;
  level: "satis" | "olasi" | "zayif" | "uygun_degil";
  level_label: string;
  need: string;
  why: string;
  priority: number | null;
  approach: string;
  what: string;
  caveat: string | null;
  evidence: PlanEvidence[];
  sources: string[];
  sector_only: boolean;
  recurring: boolean;
  guide_id: string | null;
  estimate: Estimate | null;
  evidence_note: string | null;
}
export interface ProviderItem { key: string; title: string; status: string; status_label: string; value: string | null; evidence: string | null; source: string | null; url: string | null }
export interface SalesPlan {
  business_id: number;
  analyzed: boolean;
  message?: string;
  opportunities: PlanOpportunity[];
  package?: { services: string[]; priced: { service: string; label: string }[]; unpriced: string[]; min: number | null; max: number | null; default: number | null; label: string; disclaimer: string };
  providers?: { items: ProviderItem[]; win_opportunities: { service: string; provider: string | null; source: string; text: string }[] };
  cross_check_flags?: { field: string; note: string | null; sources: { label: string; value: string }[] }[];
  scripts?: { call: string; whatsapp: string; email: { subject: string; body: string }; short_note: string; facts_used: { service: string; text: string; detail: string }[]; basis: string; caveat: string };
  why_prospect?: string[];
}

export interface FunnelStep { key: string; label: string; count: number; rate_from_previous: number | null; rate_from_analysis: number | null }
export interface Funnel {
  period: ReportPeriod;
  label: string;
  steps: FunnelStep[];
  offer_total: number;
  offer_count: number;
  offer_amount_missing: number;
  won_total: number;
  won_count: number;
  won_amount_missing: number;
  note: string;
  updated_at: string;
}
export interface RevenueRow { name: string; opportunities: number; offers: number; sales: number; amount: number; offer_amount: number; average: number | null; conversion: number | null; amount_missing: number; sample_note: string | null }
export interface Revenue { by: "service" | "sector"; period: ReportPeriod; label: string; items: RevenueRow[]; min_sample: number; note: string; updated_at: string }
export interface SalesSuggestions { items: { kind: string; text: string }[]; updated_at: string }
export interface StaffPerfRow {
  user_id: number; name: string; role: Role; is_active: boolean; analyses: number; leads_added: number; assigned_leads: number; contacts: number; unreachable: number; interested: number;
  offers_sent: number; won: number; lost: number; sales_total: number; sales_amount_missing: number; followed_customers: number; follow_ups_done: number;
  overdue_follow_ups: number; avg_follow_delay_hours: number | null; conversion_offer_to_won: number | null;
}
export interface StaffPerformance { period: ReportPeriod; label: string; items: StaffPerfRow[]; note: string; updated_at: string }
export interface SalesOverview {
  period: ReportPeriod; label: string; updated_at: string;
  metrics: { analyses: number; analyzed_businesses: number; new_leads: number; contacts: number; interested: number; offers_sent: number; won: number; won_total: number; won_amount_missing: number };
  by_service: RevenueRow[]; by_sector: RevenueRow[]; by_staff: StaffPerfRow[];
}
export interface ServicePriceRow { service_id: number; service_name: string; min_price: number | null; max_price: number | null; default_price: number | null; is_active: boolean; priced: boolean; updated_at: string | null }
export interface EmailState {
  status: "not_configured" | "saved" | "tested" | "active" | "error";
  status_icon: string; status_label: string; configured: boolean; enabled: boolean;
  host: string | null; port: number | null; username: string | null; from_name: string | null; from_email: string | null; security: "tls" | "ssl" | "none";
  securities: { key: string; label: string }[]; has_password: boolean; masked_password: string | null;
  last_test_ok: boolean | null; last_test_at: string | null; last_test_message: string | null; updated_at: string | null;
}
