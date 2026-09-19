"""SQLAlchemy models for Mchttasarım Marketing OS.

Scope: MVP (Faz 1) tables only, per docs/plans/2026-09-18-mchttasarim-marketing-os-design.md.
Faz 2-4 tables (authorized_profiles, campaign_drafts, content_plans, monthly_reports)
are added when the sprint that implements them starts.
"""

from datetime import datetime, date

from sqlalchemy import (
    ForeignKey,
    Numeric,
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
    group_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # arayüzde gruplu liste için
    # Pasif sektörler seçim listesinde görünmez; eski kayıtlar bozulmasın diye silinmek yerine pasife alınır.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
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

    # Kaynaktan gelen (doğrulanmış) ek profil verisi. Kaynakta olmayan alan buraya YAZILMAZ.
    category_label: Mapped[str | None] = mapped_column(String(120), nullable=True)  # kaynaktaki kategori (Türkçe etiket)
    maps_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # sadece kaynak gerçek bir Maps bağlantısı verdiyse
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # {"categories": [...], "primary_type": "...", "social": {...}, "photos_capped": bool, ...}

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="discovered")
    # discovered | analyzing | analyzed

    crm_stage: Mapped[str] = mapped_column(String(40), nullable=False, default="Yeni")  # bkz. packages/crm.py
    crm_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # son CRM işlemi (durum/not)
    crm_added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # dolu = CRM'de; analiz bunu ASLA doldurmaz
    staff_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # personelin serbest notu (dışa aktarmada "Personel notu")
    crm_added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # CRM'e ilk ekleyen kullanıcı
    crm_updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # son CRM işlemini yapan kullanıcı
    crm_last_action: Mapped[str | None] = mapped_column(String(300), nullable=True)  # ör. "Arandı → Teklif Gönderildi"
    # --- satış takibi (CRM): sorumlu personel, takip, teklif/satış tutarı, kayıp nedeni, ilgilenilen hizmet
    crm_owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # sorumlu personel
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # son görüşme/arama
    interested_service: Mapped[str | None] = mapped_column(String(120), nullable=True)
    offer_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)  # verilen/hazırlanan teklif tutarı (TL)
    sale_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)  # kazanılan satış tutarı (TL)
    lost_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # aramayı başlatan kullanıcı
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
    # ANALİZ GEÇMİŞİ: her satır bir analiz işlemidir (business_id + user_id + completed_at + status). Aynı firma tekrar analiz edilirse yeni satır açılır.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # analizi başlatan kullanıcı (eski kayıtlarda boş)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # user = personel isteği (arama/analiz düğmesi) · maintenance = bakım (önbellekten yeniden hesaplama; personel sayaçlarına dahil edilmez)


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


class BusinessResearch(Base):
    """Bir işletmenin çok kaynaklı araştırma sonucu: kaynak durumları, Google/Bing profilleri, web sitesi adayları,
    sosyal medya, alan bazlı çapraz doğrulama kararları. Ayrıntılar `payload` içindedir (bkz. services/research/pipeline.py)."""

    __tablename__ = "business_research"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SalesAssessment(Base):
    """Bir analiz koşusunun satış değerlendirmesi: seviye + gerekçe + önerilen hizmetler + görüşme notu.

    Tamamen kural tabanlıdır (AI yok). `payload` ekranda gösterilen web sitesi ve Google profili
    kontrol listelerini (her kontrol: durum, değer, neden önemli, satılabilecek hizmet) taşır.
    """

    __tablename__ = "sales_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)

    level: Mapped[str] = mapped_column(String(20), nullable=False)  # Yüksek | Orta | Düşük | Belirsiz
    level_reason: Mapped[str] = mapped_column(Text, nullable=False)
    rank_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # sadece sıralama için, ekranda gösterilmez
    needs_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    primary_service_id: Mapped[int | None] = mapped_column(ForeignKey("services_catalog.id"), nullable=True)
    secondary_service_id: Mapped[int | None] = mapped_column(ForeignKey("services_catalog.id"), nullable=True)
    top_opportunity: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_call: Mapped[str | None] = mapped_column(Text, nullable=True)
    talking_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    sales_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # işlemi yapan kullanıcı (eski kayıtlarda boş)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # teklif/satış tutarı, hizmet, kayıp nedeni, takip tarihi (olay ayrıntısı)
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
    """Uygulama kullanıcısı. Kullanıcılar fiziksel olarak SİLİNMEZ; pasifleştirilir (eski CRM/analiz kayıtları korunur)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # Ad Soyad
    username: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="calisan")  # yonetici | calisan | stajyer
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # scrypt (bkz. services/auth/security.py); düz metin ASLA saklanmaz
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class UserSession(Base):
    """Sunucu tarafı oturum: çerezde yalnızca rastgele token durur, veritabanında yalnızca SHA-256 özeti saklanır."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    remember: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")  # 'Beni hatırla': kalıcı çerez + uzun kayan süre
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ActivityLog(Base):
    """Personel aktivite geçmişi: kim, ne zaman, hangi firmada, ne yaptı (yalnızca eklenir)."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # başarısız girişte boş olabilir
    action: Mapped[str] = mapped_column(String(60), nullable=False)  # bkz. services/auth/activity.py ACTIONS
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id"), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # okunabilir Türkçe ayrıntı ("Arandı → Teklif Gönderildi")
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    """Sistem ayarları (ör. Google API). Sırlar yalnızca `secret_encrypted` içinde ŞİFRELİ saklanır ve arayüze asla geri gönderilmez."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class ServicePrice(Base):
    """Yönetici tarafından girilen hizmet fiyat aralıkları (kodda sabit fiyat YOK). Fiyat girilmemişse arayüz 'Fiyatlandırma yapılmadı' der."""

    __tablename__ = "service_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services_catalog.id"), nullable=False, unique=True)
    min_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    default_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PasswordResetToken(Base):
    """Tek kullanımlık, süreli şifre belirleme/sıfırlama bağlantısı. Veritabanında yalnızca token'ın SHA-256 özeti tutulur."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="reset")  # reset | invite
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserAnalysis(Base):
    """KULLANICI BAZLI analiz geçmişi: bir kullanıcının bir işletme için tamamladığı BAŞARILI analiz (user_id + business_id + analysis_type tekildir).

    'Daha önce analiz edildi' yalnızca bakan kullanıcının kendi kaydı varsa gösterilir; işletmenin sistemde bulunması ya da başka bir kullanıcının analizi bunu doğurmaz.
    Her analiz işlemi (tekrarlar dahil) ayrıca `analysis_jobs`'ta durur; bu tablo kullanıcı+işletme başına ÖZET (son başarılı analiz) tutar.
    """

    __tablename__ = "user_analyses"
    __table_args__ = (UniqueConstraint("user_id", "business_id", "analysis_type", name="uq_user_analysis"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(30), nullable=False, default="deep")
    analysis_job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"), nullable=True)
    analysis_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # özet: durum, skor, seviye (ayrıntı sales_assessments'ta)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # bu kullanıcının bu işletme için başarılı analiz sayısı
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FollowUp(Base):
    """Takip: bir işletme için bir kullanıcının planladığı geri dönüş (tarih + saat + not + durum). Bir işletmede birden çok takip olabilir."""

    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # takipten sorumlu kullanıcı
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    has_time: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")  # saat girildi mi (yoksa yalnızca gün)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Bekliyor", server_default="Bekliyor")  # Bekliyor | Tamamlandı | İptal
    result: Mapped[str | None] = mapped_column(String(60), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
