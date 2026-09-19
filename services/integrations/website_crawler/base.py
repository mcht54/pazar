"""Web sitesi analizinin ham çıktısı (yorumsuz ölçümler).

Bu katman SADECE ölçer; "sorun var mı, hangi hizmet satılır" kararı rule_engine/website_checks.py'de
verilir. Ölçülemeyen her alan None kalır — asla varsayılan bir değerle doldurulmaz.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# outcome değerleri:
#   ok                 -> sayfa alındı ve ayrıştırıldı
#   unreachable        -> site açılmıyor (DNS, zaman aşımı, 404, sunucu hatası...)
#   blocked            -> site bot korumasıyla erişimi engelledi (site bozuk DEĞİL, analiz edilemedi)
#   robots_disallowed  -> robots.txt taramaya izin vermiyor (saygı gösterilir, analiz edilemedi)
#   not_a_website      -> "web sitesi" alanında sosyal medya/harita/pazaryeri adresi var
#   invalid_url        -> adres geçersiz
OUTCOMES = ("ok", "unreachable", "blocked", "robots_disallowed", "not_a_website", "invalid_url")


@dataclass
class WebsiteSignals:
    success: bool
    outcome: str = "ok"
    error_reason: str | None = None  # kullanıcıya gösterilebilir Türkçe açıklama
    # Erişim başarısız olduysa nedenin türü: dns | timeout | connect | ssl | http_404 | http_error | redirect | private
    # (dns/http_404 kalıcı bir sorunu, timeout/connect geçici bir durumu düşündürür.)
    failure_kind: str | None = None

    # --- erişim ---
    requested_url: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    https_enabled: bool | None = None
    ssl_error: bool | None = None  # sertifika geçersiz/süresi dolmuşsa True
    response_ms: float | None = None
    html_bytes: int | None = None
    script_count: int | None = None
    stylesheet_count: int | None = None

    # --- sayfa başlığı ve SEO etiketleri ---
    title: str | None = None
    meta_description: str | None = None
    h1_texts: list[str] = field(default_factory=list)
    h2_count: int | None = None
    h3_count: int | None = None
    canonical: str | None = None
    noindex: bool | None = None
    og_tags_present: bool | None = None
    html_lang: str | None = None
    favicon_present: bool | None = None
    schema_types: list[str] = field(default_factory=list)

    # --- mobil (yalnızca viewport işareti; gerçek cihaz testi değildir) ---
    viewport_ok: bool | None = None

    # --- içerik ---
    word_count: int | None = None
    text_excerpt: str | None = None  # yerel SEO kontrolü için gövde metninin başı
    images_total: int | None = None
    images_missing_alt: int | None = None
    copyright_year: int | None = None
    generator: str | None = None
    # İçerik büyük ölçüde JavaScript ile çiziliyor olabilir (Wix/React...): statik HTML'de az metin görünür,
    # bu yüzden H1/içerik miktarı gibi kontroller güvenilir ölçülemez.
    js_rendered_hint: bool | None = None
    # İşletmeyle ilgisiz spam/yetişkin/bahis içeriği tespit edildiyse terimler (site ele geçirilmiş olabilir)
    spam_terms: list[str] = field(default_factory=list)

    # --- iletişim / dönüşüm noktaları ---
    tel_link_present: bool | None = None
    whatsapp_link_present: bool | None = None
    maps_link_present: bool | None = None  # Google Haritalar bağlantısı veya gömülü harita
    form_present: bool | None = None
    phone_in_text: bool | None = None
    email_in_text: bool | None = None
    address_in_text: bool | None = None
    social_links: dict[str, str] = field(default_factory=dict)
    # --- çapraz doğrulama için sitede GÖRÜLEN iletişim bilgileri (ana sayfa + iletişim sayfası) ---
    phones_found: list[str] = field(default_factory=list)  # normalize (10 haneli)
    emails_found: list[str] = field(default_factory=list)
    address_text: str | None = None  # sitede görülen adres benzeri metin parçası
    schema_business: dict | None = None  # JSON-LD LocalBusiness: name/telephone/email/address/same_as
    contact_page_url: str | None = None
    contact_page_fetched: bool | None = None

    # --- site yapısı (menü/bağlantılardan) ---
    has_services_page: bool | None = None
    has_about_page: bool | None = None
    has_references_page: bool | None = None
    has_blog: bool | None = None
    has_contact_page: bool | None = None
    has_appointment_link: bool | None = None
    has_shop_signals: bool | None = None  # sepet / online satış işaretleri
    # Sayfa altındaki (footer) "Tasarım: X / Designed by X" kredisi: {"name","url","text","kind"}; kind = agency | platform. Görülmediyse None
    # (yokluk "ajans yok" demek DEĞİLDİR; çoğu site kredi vermez).
    agency_credit: dict | None = None

    # --- ölçüm / reklam altyapısı ve dönüşüm (ana sayfa HTML'inden; ölçülemediyse None) ---
    # Tespit edilen izleme araçları: ga4 | universal_analytics | gtm | google_ads | meta_pixel | hotjar | clarity | yandex_metrica
    analytics_tools: list[str] | None = None
    search_console_verified: bool | None = None  # <meta name="google-site-verification"> görüldü (DNS ile doğrulanmış olabilir → yokluk kanıt değildir)
    cta_present: bool | None = None  # belirgin harekete geçirici çağrı (Hemen Ara / Randevu Al / Teklif Al …)
    internal_links_count: int | None = None
    mailto_link_present: bool | None = None
    has_catalog_page: bool | None = None  # menü / katalog / ürünler / fiyat listesi sayfası bağlantısı

    # --- teknik ---
    sitemap_present: bool | None = None
    links_checked: int | None = None
    broken_links: list[dict] = field(default_factory=list)  # [{"url": ..., "status": 404}]

    # --- Google PageSpeed (yalnızca GOOGLE_PAGESPEED_API_KEY varsa) ---
    pagespeed: dict | None = None
    pagespeed_error: str | None = None


class WebsiteAnalyzer(ABC):
    @abstractmethod
    def analyze(self, url: str, *, light: bool = False) -> WebsiteSignals:
        """light=True: yalnızca ana sayfa + iletişim sayfası (aday sitenin işletmeye ait olup olmadığını doğrulamak için);
        kırık bağlantı/sitemap/PageSpeed kontrolleri atlanır."""
        raise NotImplementedError
