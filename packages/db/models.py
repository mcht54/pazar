"""SQLAlchemy models for Mchttasarım Marketing OS.

Scope: MVP (Faz 1) tables only, per docs/plans/2026-09-18-mchttasarim-marketing-os-design.md.
Faz 2-4 tables (authorized_profiles, campaign_drafts, content_plans, monthly_reports)
are added when the sprint that implements them starts.
"""

from datetime import datetime, date

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    Date,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.db.base import Base


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)  # "il" | "ilce"
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    search_radius_m: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)

    parent: Mapped["Region"] = relationship("Region", remote_side=[id])


class Sector(Base):
    __tablename__ = "sectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    google_place_types: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    keyword_variants: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)

    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Discovery Data (Google Places, kamuya açık) ---
    # Tekil dedup anahtarı — sağlayıcıya göre "osm_node_123..." veya gerçek Google place_id olabilir.
    # İsim tarihsel (Sprint 0'da Google-only tasarlanmıştı); anlamı artık "external_ref".
    google_place_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    google_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    photo_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(String(500), nullable=True)
    discovery_source: Mapped[str] = mapped_column(String(50), nullable=False, default="google_places")

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="discovered")
    # discovered | analyzing | analyzed

    crm_stage: Mapped[str] = mapped_column(String(40), nullable=False, default="Yeni")
    opportunity_score_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sales_priority: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Yüksek | Orta | Düşük

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sector: Mapped["Sector"] = relationship("Sector")
    region: Mapped["Region"] = relationship("Region")


class DiscoveryJob(Base):
    __tablename__ = "discovery_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), nullable=False)
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # pending | running | completed | partial | failed
    found_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    found_existing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # [{"external_ref": "...", "reason": "..."}] — provider tarafında tekil kayıt hataları (partial failure)
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoveryJobResult(Base):
    __tablename__ = "discovery_job_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("discovery_jobs.id"), nullable=False)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)

    __table_args__ = (UniqueConstraint("job_id", "business_id", name="uq_discovery_job_result"),)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # pending | running | completed | partial | failed
    stages_status: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {"places": "success", "website": "success", "social": "failed", "evidence_extraction": "success",
    #  "rule_engine": "success", "scoring": "success", "competitor": "success", "ai_interpretation": "skipped"}
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessMetric(Base):
    __tablename__ = "business_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)

    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # known | unknown | unverified | not_available
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)

    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # website | gbp | social | seo | ads | visual | print
    finding: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # none | low | medium | high
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # places | website_crawl | pagespeed | social | ai_interpretation | manual
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)  # low | medium | high
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    based_on_metric_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    mchttasarim_opportunity: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_service_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CompetitorSnapshot(Base):
    __tablename__ = "competitor_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)
    competitor_business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpportunityScore(Base):
    __tablename__ = "opportunity_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)
    dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    # web | seo | google_visibility | social | ads | design | print
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100; NULL ise insufficient_data
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scored")
    # scored | insufficient_data — kanıt yoksa skor uydurulmaz, insufficient_data ile işaretlenir
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    based_on_finding_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)


class ServiceCatalog(Base):
    __tablename__ = "services_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_sectors: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    required_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    opportunity_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sales_arguments: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    deliverables: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    default_priority: Mapped[str] = mapped_column(String(20), nullable=False, default="Orta")


class ServiceRecommendation(Base):
    __tablename__ = "service_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services_catalog.id"), nullable=False)
    matched_rule: Mapped[str] = mapped_column(Text, nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_justification: Mapped[str | None] = mapped_column(Text, nullable=True)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    problems_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    opportunities_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_services: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scope_of_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_items: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrmActivity(Base):
    __tablename__ = "crm_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # status_change | note | call | meeting
    from_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiUsageLedger(Base):
    __tablename__ = "api_usage_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_name: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cost_units: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    quota_period: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "2026-09-18" (daily bucket)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id"), nullable=True)


class IntegrationRegistry(Base):
    __tablename__ = "integrations_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    terms_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    quota_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cache_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requires_oauth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attribution_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed_at: Mapped[date] = mapped_column(Date, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
