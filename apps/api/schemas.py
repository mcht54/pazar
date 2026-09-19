from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    parent_region_id: int | None
    level: str
    search_radius_m: int


class SectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    group_name: str | None = None


class DiscoveryJobCreate(BaseModel):
    region_id: int
    sector_id: int
    target_count: int = 30
    auto_analyze: bool = True  # bulunan işletmeler için Google profili + web sitesi analizini otomatik başlat


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
    # Analiz ilerlemesi (hesaplanır)
    total_count: int = 0
    analyzed_count: int = 0
    analyzing_count: int = 0
    failed_analysis_count: int = 0


class BusinessOut(BaseModel):
    """İşletme kartı: kaynak verisi + (varsa) satış değerlendirmesi özeti.

    Değeri None olan her alan "Doğrulanamadı" demektir — kaynak vermediği için gösterilemez, tahmin edilmez.
    """

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sector_id: int
    sector_name: str = ""
    region_id: int
    region_label: str = ""
    address: str | None
    phone: str | None
    website: str | None
    email: str | None
    lat: float | None = None
    lng: float | None = None
    google_rating: float | None
    google_review_count: int | None
    photo_count: int | None
    opening_hours: str | None
    category_label: str | None = None
    maps_url: str | None = None
    maps_search_url: str = ""
    last_review_at: datetime | None = None

    discovery_source: str
    source_label: str = ""
    source_url: str | None = None
    source_checked_at: datetime | None = None
    is_demo_data: bool = False

    status: str
    crm_stage: str
    last_analysis_at: datetime | None

    # --- satış değerlendirmesi özeti (analiz edildiyse) ---
    sales_level: str | None = None  # Yüksek | Orta | Düşük | Belirsiz
    sales_reason: str | None = None
    needs_verification: bool | None = None
    primary_service: str | None = None
    secondary_service: str | None = None
    top_opportunity: str | None = None
    gap_summary: list[str] = Field(default_factory=list)
    why_call: str | None = None
    sales_note: str | None = None
    gbp_summary: str | None = None
    web_summary: str | None = None
    # --- çok kaynaklı araştırma (Google + Bing + resmi site + OSM) ---
    verification: dict[str, dict] = Field(default_factory=dict)  # alan -> {value, status, sources, note, checked}
    source_statuses: list[dict] = Field(default_factory=list)  # kaynak -> KONTROL EDİLDİ / ERİŞİLEMEDİ / EŞLEŞME YOK
    social_accounts: list[dict] = Field(default_factory=list)
    web_quick: list[dict] = Field(default_factory=list)  # kart üzerinde: [{"label","state","value"}] — Title: VAR, Meta description: YOK ...
    gbp_quick: list[dict] = Field(default_factory=list)
    talking_point: str | None = None
    # --- satış puanı, CRM, tekrar tarama ---
    sales_score: int | None = None  # 0-100 (gerçek tespitlere dayalı; ayrıntısı detayda "Neden bu puanı aldı?")
    score_band: str | None = None
    top_problem: str | None = None
    staff_note: str | None = None
    crm_updated_at: datetime | None = None
    previously_analyzed: bool = False  # BAKAN kullanıcı bu işletmeyi bu aramadan ÖNCE kendisi başarıyla analiz etmiş mi (başkasının analizi sayılmaz)
    analyzed_by_me: bool = False  # bakan kullanıcının bu işletme için başarılı analizi var mı
    analyzed_by_me_at: datetime | None = None
    analyzed_by_others: bool = False  # sistemde analiz verisi var ama bakan kullanıcının kendi analizi yok
    # --- CRM üyeliği (analiz firmayı CRM'e eklemez; CRM'de olmak ayrı ve bilinçli bir işlemdir)
    in_crm: bool = False
    crm_added_at: datetime | None = None
    crm_added_by_name: str | None = None  # CRM'e ilk ekleyen (eski kayıtlarda "Bilinmiyor (eski kayıt)")
    crm_updated_by_name: str | None = None  # son CRM işlemini yapan
    crm_last_action: str | None = None  # ör. "Arandı → Teklif Gönderildi"
    # --- satış takibi (CRM'deki firmalar)
    crm_owner_id: int | None = None
    crm_owner_name: str | None = None
    next_follow_up_at: datetime | None = None
    follow_up_note: str | None = None
    follow_up_state: str | None = None  # overdue | today | upcoming
    last_contact_at: datetime | None = None
    interested_service: str | None = None
    offer_amount: float | None = None
    sale_amount: float | None = None
    lost_reason: str | None = None
    # --- analiz durumu (⏳ ✅ ⚠️ ❌ ⚪) ve son analizi yapan
    analysis_state: str = "none"  # none | running | completed | partial | failed
    analysis_state_label: str = "Henüz analiz edilmedi"
    last_analyzed_by_name: str | None = None
    # --- satış öncelik sıralaması (skor + fırsat sayısı + ticari anlamlılık + tamamlanma) ve nedeni
    priority_score: float | None = None
    priority_reasons: list[str] = Field(default_factory=list)
    why_prospect: list[str] = Field(default_factory=list)  # "🔥 Neden potansiyel müşteri?" — gerçek analiz bulguları
    top_guide_id: str | None = None  # kartta "💡 Nasıl Çözülür?" için en önemli fırsatın rehberi
    province_name: str | None = None
    district_name: str | None = None
    # --- müşteri adayı uygunluğu: rakip / kamu kurumu / Mchttasarım'ın kendisi ise dolu (panelde listelenmez; puanı etkilemez)
    prospect_kind: str | None = None
    prospect_label: str | None = None
    prospect_reason: str | None = None


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


class AssessmentOut(BaseModel):
    """Satış değerlendirmesi — ekranın ana içeriği."""

    level: str
    level_reason: str
    needs_verification: bool
    primary_service: str | None
    secondary_service: str | None
    top_opportunity: str | None
    why_call: str | None
    talking_point: str | None
    sales_note: str | None
    gaps: list[dict]
    strengths: list[dict]
    services: list[dict]
    possible_services: list[dict]
    verification_steps: list[str]
    website: dict
    gbp: dict
    social: list[dict] = Field(default_factory=list)
    opportunities: dict = Field(default_factory=dict)  # {"evidence": [...], "possible": [...]}
    score: dict = Field(default_factory=dict)  # {"score", "band", "groups", "items", "adjustments", "assumptions", "summary", "note"}
    service_matrix: dict = Field(default_factory=dict)  # {"items": [hizmet başına 🟢🟡⚪🔴 + kanıt + gerekçe], "counts", "top"}
    priority: dict = Field(default_factory=dict)  # {"value", "components", "weights", "reasons"} — potansiyel müşteri sıralaması
    why_prospect: list[str] = Field(default_factory=list)
    analyzed_at: datetime


class BusinessDetailOut(BaseModel):
    business: BusinessOut
    assessment: AssessmentOut | None
    metrics: list[BusinessMetricOut]
    findings: list[FindingOut]
    service_recommendations: list[ServiceRecommendationOut]
    competitors: list[CompetitorMetricRow]
    latest_analysis_job: AnalysisJobOut | None
    crm_history: list[dict] = Field(default_factory=list)
    follow_ups: list[dict] = Field(default_factory=list)  # bekleyen takipler + son kapananlar
    analysis_history: list[dict] = Field(default_factory=list)  # her analiz işlemi: kim · ne zaman · durum


class AnalyzeBulkRequest(BaseModel):
    business_ids: list[int] | None = None
    top_n: int | None = None


class CrmSalesFields(BaseModel):
    """Satış takibi alanları: yalnızca istekte GÖNDERİLEN alanlar işlenir (null göndermek alanı temizler)."""
    follow_up_at: str | None = None  # 'YYYY-MM-DD' ya da ISO tarih-saat (Europe/Istanbul)
    follow_up_note: str | None = None
    offer_amount: float | str | None = None
    sale_amount: float | str | None = None
    lost_reason: str | None = None
    interested_service: str | None = None
    owner_id: int | None = None

    def provided(self) -> dict:
        return {k: getattr(self, k) for k in self.model_fields_set if k in CrmSalesFields.model_fields}


class CrmUpdate(CrmSalesFields):
    stage: str | None = None
    staff_note: str | None = None  # CRM notu (kalıcı, güncel not)


class ContactIn(BaseModel):
    channel: str = "arama"  # arama | whatsapp | eposta | yuz_yuze
    result: str  # Ulaşılamadı | Görüşüldü | İlgileniyor | Teklif istendi | İlgilenmiyor | Daha sonra aranacak
    note: str | None = None


class FollowUpComplete(BaseModel):
    result: str
    note: str | None = None
    next_follow_up_at: str | None = None


class CrmAdd(CrmSalesFields):
    stage: str = "Aranacak"
    note: str | None = None


class ExportRequest(BaseModel):
    ids: list[int]
    format: str = "csv"  # csv | xlsx
