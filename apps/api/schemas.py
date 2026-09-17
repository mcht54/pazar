from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    parent_region_id: int | None
    level: str


class SectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class DiscoveryJobCreate(BaseModel):
    region_id: int
    sector_id: int
    target_count: int = 10


class DiscoveryJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    region_id: int
    sector_id: int
    target_count: int
    status: str
    found_new: int
    found_existing: int
    item_errors: list[dict]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sector_id: int
    region_id: int
    address: str | None
    phone: str | None
    website: str | None
    google_rating: float | None
    google_review_count: int | None
    photo_count: int | None
    discovery_source: str
    is_demo_data: bool = False
    status: str
    crm_stage: str
    opportunity_score_total: int | None
    sales_priority: str | None
    created_at: datetime
    last_analysis_at: datetime | None

    @classmethod
    def from_orm_business(cls, business):
        data = cls.model_validate(business)
        data.is_demo_data = business.discovery_source == "mock_demo"
        return data


class BusinessMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    metric_key: str
    value: dict | None
    unit: str | None
    status: str
    source: str
    collected_at: datetime


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    finding: str
    severity: str
    evidence: str
    source: str
    confidence: str
    detected_at: datetime
    based_on_metric_ids: list[int]
    business_impact: str | None
    mchttasarim_opportunity: str | None
    recommended_service_ids: list[int]


class OpportunityScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dimension: str
    score: int | None
    status: str
    reasoning: str
    based_on_finding_ids: list[int]


class ServiceRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    service_id: int
    service_name: str
    priority_rank: int
    matched_rule: str
    ai_justification: str | None


class CompetitorMetricRow(BaseModel):
    metric_key: str
    business_value: dict | None
    business_status: str
    competitors: list[dict]  # [{competitor_id, competitor_name, value, status}]


class AnalysisJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    business_id: int
    status: str
    stages_status: dict
    started_at: datetime | None
    completed_at: datetime | None


class BusinessDetailOut(BaseModel):
    business: BusinessOut
    metrics: list[BusinessMetricOut]
    findings: list[FindingOut]
    opportunity_scores: list[OpportunityScoreOut]
    service_recommendations: list[ServiceRecommendationOut]
    competitors: list[CompetitorMetricRow]
    latest_analysis_job: AnalysisJobOut | None


class AnalyzeBulkRequest(BaseModel):
    business_ids: list[int] | None = None
    top_n: int | None = None
