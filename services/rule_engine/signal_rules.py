"""Deterministik sinyal → Finding içeriği kuralları.

Bu dosya "Rule Engine"in kalbidir: hangi ölçülen sinyalin hangi Finding'e ve
hangi Mchttasarım hizmetine karşılık geldiğini tanımlar. AI bu tabloya
katkıda bulunmaz; sadece burada üretilmiş Finding'leri yorumlayabilir.

Her kural: category, finding etiketi, severity, evidence şablonu,
business_impact, mchttasarim_opportunity, ve services_catalog.service_name
listesi (recommended_service_ids'e çözülür).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalRule:
    signal_key: str
    category: str  # website | gbp | social | seo | ads | visual | print
    finding: str
    severity: str  # none | low | medium | high
    evidence_template: str
    source: str
    confidence: str
    business_impact: str
    mchttasarim_opportunity: str
    service_names: tuple[str, ...]


SIGNAL_RULES: dict[str, SignalRule] = {
    "website_missing": SignalRule(
        signal_key="website_missing",
        category="website",
        finding="Web sitesi tespit edilemedi",
        severity="high",
        evidence_template="Google Places kaydında website alanı boş (place_id: {google_place_id}).",
        source="places",
        confidence="high",
        business_impact="İşletme aramalarda ve sosyal medya bio/link alanlarında yönlendirebileceği bir dijital adrese sahip değil; potansiyel müşteri kaybı riski var.",
        mchttasarim_opportunity="Web sitesi olmayan işletme, web tasarım hizmeti için doğrudan aday.",
        service_names=("Web Tasarım",),
    ),
    "website_unreachable": SignalRule(
        signal_key="website_unreachable",
        category="website",
        finding="Web sitesine erişilemedi",
        severity="medium",
        evidence_template="{website} adresine bağlantı denemesi başarısız oldu: {error_reason}",
        source="website_crawl",
        confidence="medium",
        business_impact="Web sitesi kayıtlı olsa da potansiyel müşteriler siteye ulaşamıyor olabilir.",
        mchttasarim_opportunity="Web sitesi bakımı/yenilenmesi ihtiyacı olabilir.",
        service_names=("Web Tasarım",),
    ),
    "https_missing": SignalRule(
        signal_key="https_missing",
        category="website",
        finding="Web sitesi HTTPS kullanmıyor",
        severity="medium",
        evidence_template="{website} adresi HTTPS üzerinden servis edilmiyor.",
        source="website_crawl",
        confidence="high",
        business_impact="Tarayıcılar 'güvenli değil' uyarısı gösterebilir, ziyaretçi güveni azalır.",
        mchttasarim_opportunity="Web sitesi yenileme kapsamında SSL/HTTPS kurulmalı.",
        service_names=("Web Tasarım",),
    ),
    "title_missing": SignalRule(
        signal_key="title_missing",
        category="seo",
        finding="Sayfa title etiketi mevcut değil",
        severity="medium",
        evidence_template="HTML head içinde dolu bir <title> elementi bulunamadı ({website}).",
        source="website_crawl",
        confidence="high",
        business_impact="Arama sonuçlarında ve tarayıcı sekmesinde işletme adı yerine boş/otomatik başlık görünür.",
        mchttasarim_opportunity="On-page SEO optimizasyonu",
        service_names=("SEO",),
    ),
    "meta_description_missing": SignalRule(
        signal_key="meta_description_missing",
        category="seo",
        finding="Homepage meta description mevcut değil",
        severity="medium",
        evidence_template="HTML head içinde meta[name='description'] elementi bulunamadı ({website}).",
        source="website_crawl",
        confidence="high",
        business_impact="Arama sonuçlarında açıklama metni eksik/otomatik oluşturuluyor, tıklama oranı düşebilir.",
        mchttasarim_opportunity="On-page SEO optimizasyonu",
        service_names=("SEO",),
    ),
    "h1_missing": SignalRule(
        signal_key="h1_missing",
        category="seo",
        finding="Sayfada H1 başlık etiketi bulunamadı",
        severity="medium",
        evidence_template="Homepage HTML'inde <h1> etiketi tespit edilemedi ({website}).",
        source="website_crawl",
        confidence="high",
        business_impact="Arama motorları sayfanın ana konusunu daha zor anlar, SEO görünürlüğü zayıflar.",
        mchttasarim_opportunity="On-page SEO optimizasyonu",
        service_names=("SEO",),
    ),
    "schema_missing": SignalRule(
        signal_key="schema_missing",
        category="seo",
        finding="LocalBusiness yapılandırılmış verisi (schema) bulunamadı",
        severity="low",
        evidence_template="Homepage HTML'inde application/ld+json schema bloğu tespit edilemedi ({website}).",
        source="website_crawl",
        confidence="medium",
        business_impact="Google, işletme bilgilerini (adres/saat/puan) arama sonucunda zenginleştiremiyor.",
        mchttasarim_opportunity="Local SEO / schema markup ekleme",
        service_names=("SEO",),
    ),
    "no_cta_link": SignalRule(
        signal_key="no_cta_link",
        category="website",
        finding="Sitede doğrudan iletişim/CTA bağlantısı bulunamadı",
        severity="medium",
        evidence_template="Homepage'de WhatsApp, tel: veya rezervasyon linki tespit edilemedi ({website}).",
        source="website_crawl",
        confidence="medium",
        business_impact="Ziyaretçinin işletmeyle iletişime geçmesi zorlaşıyor, dönüşüm oranı düşebilir.",
        mchttasarim_opportunity="Web sitesi yenileme kapsamında CTA/iletişim entegrasyonu eklenmeli.",
        service_names=("Web Tasarım",),
    ),
    "social_not_linked": SignalRule(
        signal_key="social_not_linked",
        category="social",
        finding="Website üzerinden sosyal medya hesabına ulaşılamadı",
        severity="low",
        evidence_template="{website} sayfasında Instagram/Facebook linkine rastlanmadı (hesabın var olmadığı anlamına gelmez).",
        source="social",
        confidence="low",
        business_impact="Web sitesi ziyaretçileri sosyal medya hesabına yönlendirilemiyor.",
        mchttasarim_opportunity="Sosyal medya varlığının güçlendirilmesi/entegrasyonu",
        service_names=("Sosyal Medya Yönetimi",),
    ),
    "low_review_count": SignalRule(
        signal_key="low_review_count",
        category="gbp",
        finding="Google yorum sayısı düşük",
        severity="medium",
        evidence_template="Google Places kaydında {review_count} yorum bulunuyor (bölge/sektör ortalamasının altında kabul edilen eşik: {threshold}).",
        source="places",
        confidence="high",
        business_impact="Düşük yorum sayısı, potansiyel müşterilerin güven duymasını zorlaştırır ve Google Haritalar sıralamasını olumsuz etkiler.",
        mchttasarim_opportunity="Google Business profil/yorum yönetimi",
        service_names=("Google Business Optimizasyonu",),
    ),
    "low_photo_count": SignalRule(
        signal_key="low_photo_count",
        category="gbp",
        finding="Google Business profilinde yetersiz sayıda fotoğraf",
        severity="low",
        evidence_template="Google Places kaydında {photo_count} fotoğraf bulunuyor (eşik: {threshold}).",
        source="places",
        confidence="high",
        business_impact="Az sayıda fotoğraf, işletmenin Google Haritalar'da daha az ilgi çekici görünmesine yol açar.",
        mchttasarim_opportunity="Profesyonel fotoğraf/grafik tasarım ile profil zenginleştirme",
        service_names=("Grafik Tasarım", "Google Business Optimizasyonu"),
    ),
}

LOW_REVIEW_COUNT_THRESHOLD = 15
LOW_PHOTO_COUNT_THRESHOLD = 3

# category -> opportunity_scores.dimension eşlemesi
CATEGORY_TO_DIMENSION = {
    "website": "web",
    "seo": "seo",
    "gbp": "google_visibility",
    "social": "social",
    "ads": "ads",
    "visual": "design",
    "print": "print",
}

SEVERITY_SCORE_PENALTY = {"high": 30, "medium": 15, "low": 8, "none": 0}

ALL_DIMENSIONS = ["web", "seo", "google_visibility", "social", "ads", "design", "print"]
