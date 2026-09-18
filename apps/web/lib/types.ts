export interface Region {
  id: number;
  name: string;
  parent_region_id: number | null;
  level: "il" | "ilce";
}

export interface Sector {
  id: number;
  name: string;
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
}

export interface Business {
  id: number;
  name: string;
  sector_id: number;
  region_id: number;
  address: string | null;
  phone: string | null;
  website: string | null;
  google_rating: number | null;
  google_review_count: number | null;
  photo_count: number | null;
  opening_hours: string | null;
  discovery_source: string;
  is_demo_data: boolean;
  status: "discovered" | "analyzing" | "analyzed";
  crm_stage: string;
  opportunity_score_total: number | null;
  sales_priority: string | null;
  created_at: string;
  last_analysis_at: string | null;
}

export interface BusinessMetric {
  id: number;
  metric_key: string;
  value: { value: unknown; error_reason?: string } | null;
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

export interface OpportunityScore {
  dimension: string;
  score: number | null;
  status: "scored" | "insufficient_data";
  reasoning: string;
  based_on_finding_ids: number[];
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

export interface BusinessDetail {
  business: Business;
  metrics: BusinessMetric[];
  findings: Finding[];
  opportunity_scores: OpportunityScore[];
  service_recommendations: ServiceRecommendation[];
  competitors: CompetitorMetricRow[];
  latest_analysis_job: AnalysisJob | null;
}
