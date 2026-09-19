"""Web sitesi ve Google İşletme Profili kontrolleri (deterministik — AI yok).

Her kontrol bir `Check` üretir:
- status="ok"       -> ölçüldü, sorun yok
- status="problem"  -> ölçüldü, somut bir eksik var (kanıt cümlesiyle)
- status="unknown"  -> ölçülemedi/erişilemedi -> ekranda "Doğrulanamadı"; ASLA sorun gibi sayılmaz

Sorun bulunan kontrolde "neden önemli" (why) ve "Mchttasarım burada ne satabilir" (services) bulunur.
Kanıt cümleleri gerçek ölçülen değerleri içerir (ör. title metni, karakter sayısı).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median

from packages.localization import fold
from services.integrations.website_crawler.base import WebsiteSignals
from services.rule_engine.sector_profiles import SectorProfile

# Mchttasarım hizmet adları (services_catalog.service_name ile birebir aynı olmalı)
SVC_WEB = "Web Tasarım"
SVC_CORPORATE_SITE = "Kurumsal Web Sitesi"
SVC_ECOM = "E-Ticaret"
SVC_SEO = "Kurumsal SEO"
SVC_GBP = "Google İşletme Profili Optimizasyonu"
SVC_ADS = "Google Ads"
SVC_SOCIAL = "Sosyal Medya Yönetimi"
SVC_GRAPHIC = "Grafik Tasarım"
SVC_PRINT = "Matbaa"
SVC_BANNER = "Branda Baskı"
SVC_SIGN = "Tabela"
SVC_PROMO = "Promosyon Ürünleri"
SVC_LOCAL_SEO = "Yerel SEO"
SVC_SOCIAL_ADS = "Sosyal Medya Reklamları"
SVC_BRAND = "Kurumsal Kimlik"
SVC_MEDIA = "Fotoğraf ve Video İçerik"

GENERIC_TITLES = {"ana sayfa", "anasayfa", "home", "homepage", "welcome", "hosgeldiniz", "hos geldiniz", "untitled", "index", "default"}
STALE_COPYRIGHT_YEARS = 3
SLOW_RESPONSE_MS = 3000
OK_RESPONSE_MS = 2000
LOW_REVIEW_THRESHOLD = 15
LOW_PHOTO_THRESHOLD = 5


@dataclass
class Check:
    key: str
    area: str  # "website" | "gbp"
    label: str
    status: str  # ok | problem | unknown
    value: str  # kullanıcıya gösterilen kısa sonuç
    detail: str = ""  # kanıt cümlesi
    severity: str = "none"  # high | medium | low (problem ise)
    confidence: str = "high"  # high | medium | low
    why: str = ""  # bu eksik neden önemli
    services: tuple[str, ...] = ()  # Mchttasarım burada ne satabilir
    category: str = "website"  # website | seo | gbp | social
    source: str = "website_crawl"  # places | listing | website_crawl | pagespeed
    short: str = ""  # cümle içinde kullanılacak kısa ad
    needs_verification: bool = False
    raw: object = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "area": self.area,
            "label": self.label,
            "status": self.status,
            "value": self.value,
            "detail": self.detail,
            "severity": self.severity,
            "confidence": self.confidence,
            "why": self.why,
            "services": list(self.services),
            "needs_verification": self.needs_verification,
        }


@dataclass
class AnalysisContext:
    business_name: str
    sector_name: str
    profile: SectorProfile
    sector_phrases: list[str]  # sektörün Türkçe anahtar ifadeleri (ör. ["işitme cihazı", "işitme merkezi"])
    place_names: list[str]  # [ilçe, il] — yerel SEO kontrolü için
    source: str  # Business.discovery_source
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    peer_review_counts: list[int] = field(default_factory=list)  # aynı sektör/bölgedeki rakiplerin yorum sayıları
    sector_group: str | None = None
    research: dict | None = None  # services/research sonucu (kaynak durumları, Google/Bing profili, site, sosyal medya, kararlar)
    # Aynı bölge+sektördeki, sitesi ölçülmüş rakiplerde bir özelliğin yaygınlığı: {"has_services_page": (var_olan, ölçülen), ...}
    peer_web: dict = field(default_factory=dict)

    @property
    def google_profile(self) -> dict | None:
        """Google Haritalar'dan GÜVENLE eşleştirilip okunan profil (yoksa None)."""
        return (self.research or {}).get("google")

    def source_status(self, key: str) -> dict | None:
        return next((s for s in (self.research or {}).get("sources", []) if s["key"] == key), None)

    @property
    def social(self) -> list[dict]:
        return (self.research or {}).get("social", [])

    @property
    def conflicts(self) -> list[dict]:
        return [v for v in (self.research or {}).get("verdicts", {}).values() if v.get("status") == "celiskili"]

    @property
    def is_google_data(self) -> bool:
        return self.google_profile is not None or self.source in ("google_places", "mock_demo")

    @property
    def main_phrase(self) -> str:
        return self.sector_phrases[0] if self.sector_phrases else self.sector_name.lower()

    @property
    def place(self) -> str:
        return self.place_names[0] if self.place_names else ""


def mentions(text: str | None, phrase: str) -> bool:
    """Metinde ifade geçiyor mu? Türkçe ekleri (restoranı, Sakarya'da) tolere eden kelime-başı eşleşmesi."""
    if not text or not phrase:
        return False
    folded_text, folded_phrase = fold(text), fold(phrase)
    if not folded_phrase:
        return False
    if " " in folded_phrase:
        return folded_phrase in folded_text
    tokens = folded_text.split()
    if len(folded_phrase) < 4:
        return folded_phrase in tokens
    return any(token.startswith(folded_phrase) for token in tokens)


def _mentions_any(text: str | None, phrases: list[str]) -> bool:
    return any(mentions(text, p) for p in phrases)


# ============================================================================ WEB SİTESİ
def build_website_checks(ctx: AnalysisContext, website: str | None, signals: WebsiteSignals | None) -> list[Check]:
    checks: list[Check] = []

    # ---- web sitesi var mı?
    if not website:
        google = ctx.is_google_data
        if ctx.google_profile is not None:
            checks.append(
                Check(
                    key="presence", area="website", label="Web sitesi", status="problem",
                    value="Web sitesi bulunamadı",
                    detail="İşletmeye ait doğrulanmış bir web sitesi bulunamadı: Google İşletme Profilinde web sitesi alanı boş; Bing Haritalar, "
                    "marka adından türetilen alan adı adayları ve arama sonuçları da işletmeye ait bir site vermedi.",
                    severity="high", confidence="high",
                    why="Web sitesi olmayan işletme, Google'da arama yapan potansiyel müşterilere kendini gösteremez ve güven veremez.",
                    services=(SVC_CORPORATE_SITE, SVC_LOCAL_SEO), category="website", source="places",
                    short="web sitesinin bulunamaması", needs_verification=False,
                )
            )
            return checks
        checks.append(
            Check(
                key="presence", area="website", label="Web sitesi", status="problem",
                value="Web sitesi bulunamadı",
                detail=(
                    "Google İşletme Profilinde web sitesi alanı boş."
                    if google
                    else "Keşif kaydında web sitesi yok ve Google Haritalar profili okunamadığı için doğrulanamadı; işletmenin gerçekte sitesi "
                    "olup olmadığı kayıttan anlaşılamaz. Aramadan önce Google'da kısaca kontrol edin."
                ),
                severity="high", confidence="high" if google else "medium",
                why="Web sitesi olmayan işletme, Google'da arama yapan potansiyel müşterilere kendini gösteremez ve güven veremez.",
                services=(SVC_CORPORATE_SITE,), category="website", source="places" if google else "listing",
                short="web sitesinin bulunamaması", needs_verification=not google,
            )
        )
        return checks

    if signals is None:
        checks.append(Check(key="access", area="website", label="Web sitesi analizi", status="unknown",
                            value="Doğrulanamadı — site henüz analiz edilmedi", category="website"))
        return checks

    checks.append(Check(key="presence", area="website", label="Web sitesi", status="ok", value=website, category="website"))

    # ---- açılmayan / analiz edilemeyen site
    if not signals.success:
        checks.append(_access_check(signals))
        return checks

    checks.append(
        Check(key="access", area="website", label="Site erişimi", status="ok",
              value=f"Site açılıyor (HTTP {signals.http_status})", category="website")
    )

    text_sources = " ".join(filter(None, [signals.title, signals.meta_description, " ".join(signals.h1_texts)]))

    spam = _spam_check(signals)
    if spam is not None:
        checks.append(spam)
    brand = _brand_check(ctx, signals)
    if brand is not None:
        checks.append(brand)
    checks.append(_https_check(signals))
    checks.append(_mobile_check(signals))
    checks.append(_speed_check(signals))
    checks.append(_title_check(signals))
    checks.append(_title_keyword_check(ctx, signals))
    checks.append(_meta_description_check(signals))
    checks.append(_h1_check(signals))
    checks.append(_heading_structure_check(signals))
    checks.append(_local_seo_check(ctx, signals, text_sources))
    checks.append(_content_volume_check(signals))
    checks.append(_schema_check(signals))
    checks.append(_indexing_check(signals))
    checks.append(_sitemap_check(signals))
    checks.append(_phone_click_check(signals))
    checks.append(_whatsapp_check(signals))
    checks.append(_maps_check(ctx, signals))
    checks.append(_conversion_check(signals))
    checks.append(_booking_check(ctx, signals))
    checks.append(_services_page_check(signals))
    checks.append(_about_check(signals))
    checks.append(_references_check(signals))
    checks.append(_blog_check(signals))
    checks.append(_images_check(signals))
    checks.append(_broken_links_check(signals))
    if not ctx.social:  # araştırma sosyal medya bulgusu vermediyse sitedeki bağlantılardan (eski davranış)
        checks.append(_social_link_check(signals))
    checks.append(_freshness_check(ctx, signals))
    checks.append(_analytics_check(signals))
    checks.append(_cta_check(signals))
    checks.append(_internal_links_check(signals))
    checks.append(_peer_gap_check(ctx, signals))
    if ctx.profile.sells_products:
        checks.append(_ecommerce_check(signals))
    return [c for c in checks if c is not None]


# ---------------------------------------------------------------- ölçüm altyapısı, CTA, iç bağlantı, rakip içerik farkı
_TOOL_LABELS = {"ga4": "Google Analytics 4", "universal_analytics": "Universal Analytics", "gtm": "Google Etiket Yöneticisi", "google_ads": "Google Ads etiketi",
                "meta_pixel": "Meta (Facebook) Pixel", "hotjar": "Hotjar", "clarity": "Microsoft Clarity", "yandex_metrica": "Yandex Metrica"}


def _analytics_check(s: WebsiteSignals) -> Check | None:
    if s.analytics_tools is None:
        return None  # ölçülmedi (eski kayıt / mock): "yok" iddiası yapılmaz
    if s.js_rendered_hint:
        return Check(key="analytics", area="website", label="Ölçüm / reklam altyapısı", status="unknown",
                     value="Doğrulanamadı — içerik JavaScript ile yükleniyor, izleme kodu statik HTML'de görülemeyebilir", category="seo")
    if s.analytics_tools:
        names = ", ".join(_TOOL_LABELS.get(t, t) for t in s.analytics_tools)
        extra = " Search Console doğrulama etiketi de görüldü." if s.search_console_verified else ""
        return Check(key="analytics", area="website", label="Ölçüm / reklam altyapısı", status="ok", value=names + extra, category="seo")
    return Check(
        key="analytics", area="website", label="Ölçüm / reklam altyapısı", status="problem",
        value="Ziyaretçi ölçümü (Google Analytics/Etiket Yöneticisi) ve reklam etiketi tespit edilmedi",
        detail="Ana sayfa kaynak kodunda Google Analytics, Google Etiket Yöneticisi, Google Ads dönüşüm etiketi veya Meta Pixel bulunamadı."
               + ("" if s.search_console_verified else " Search Console doğrulama etiketi de görülmedi (başka yöntemle doğrulanmış olabilir)."),
        severity="medium", confidence="medium",
        why="Ölçüm altyapısı yoksa siteye kaç kişinin geldiği, hangi işlemlerin müşteri getirdiği bilinemez; reklam (Google Ads) yatırımı da ölçülemez ve optimize edilemez.",
        services=(SVC_SEO,), category="seo", short="ölçüm/dönüşüm takibinin olmaması", needs_verification=False,
    )


def _cta_check(s: WebsiteSignals) -> Check | None:
    if s.cta_present is None or s.js_rendered_hint:
        return None
    if s.cta_present:
        return Check(key="cta", area="website", label="Harekete geçirici çağrı (CTA)", status="ok", value="Belirgin çağrı var", category="website")
    return Check(key="cta", area="website", label="Harekete geçirici çağrı (CTA)", status="problem", value="Belirgin harekete geçirici çağrı (Hemen Ara / Randevu Al / Teklif Al) yok",
                 detail="Ana sayfadaki bağlantı ve düğme metinlerinde 'Hemen Ara', 'Randevu Al', 'Teklif Al' gibi bir çağrı bulunamadı.",
                 severity="low", confidence="medium", why="Ziyaretçiye ne yapması gerektiğini söylemeyen sayfa, ilgiyi müşteriye çevirmekte zorlanır.",
                 services=(SVC_WEB,), category="website", short="belirgin CTA'nın olmaması")


def _internal_links_check(s: WebsiteSignals) -> Check | None:
    if s.internal_links_count is None or s.js_rendered_hint:
        return None
    if s.internal_links_count >= 5:
        return Check(key="internal_links", area="website", label="İç bağlantılar", status="ok", value=f"{s.internal_links_count} iç bağlantı", category="seo")
    return Check(key="internal_links", area="website", label="İç bağlantılar", status="problem", value=f"Ana sayfada yalnızca {s.internal_links_count} iç bağlantı var",
                 detail="Ana sayfadan diğer sayfalara giden iç bağlantı sayısı çok az; site tek sayfa gibi çalışıyor.", severity="low", confidence="medium",
                 why="İç bağlantılar hem ziyaretçiyi hizmet sayfalarına taşır hem de Google'ın siteyi keşfetmesine yardım eder.",
                 services=(SVC_SEO,), category="seo", short="zayıf iç bağlantı yapısı")


_PEER_FEATURES = {
    "has_services_page": "hizmet/ürün sayfaları", "has_blog": "blog/içerik bölümü", "whatsapp_link_present": "WhatsApp bağlantısı",
    "form_present": "iletişim/randevu formu", "has_appointment_link": "randevu/rezervasyon bağlantısı", "schema": "yerel işletme (schema) verisi",
    "has_references_page": "referans/galeri sayfası",
}


def _peer_gap_check(ctx: AnalysisContext, s: WebsiteSignals) -> Check | None:
    """Aynı bölge ve sektördeki (analiz edilmiş, sitesi ölçülmüş) rakiplerin çoğunda olan ama bu sitede olmayan içerik/özellikler."""
    if not ctx.peer_web:
        return None
    mine = {"has_services_page": s.has_services_page, "has_blog": s.has_blog, "whatsapp_link_present": s.whatsapp_link_present, "form_present": s.form_present,
            "has_appointment_link": s.has_appointment_link, "schema": bool(s.schema_types), "has_references_page": s.has_references_page}
    gaps = []
    for key, label in _PEER_FEATURES.items():
        have, measured = ctx.peer_web.get(key, (0, 0))
        if measured >= 3 and have / measured >= 0.6 and mine.get(key) is False:
            gaps.append((label, have, measured))
    if not gaps:
        return Check(key="peer_gap", area="website", label="Rakiplere göre içerik", status="ok", value="Rakiplerin yaygın özelliklerinin eksiği tespit edilmedi", category="seo")
    text = "; ".join(f"{label} ({have}/{measured} rakipte var)" for label, have, measured in gaps)
    return Check(key="peer_gap", area="website", label="Rakiplere göre içerik", status="problem", value=f"Rakiplerin çoğunda olan {len(gaps)} özellik bu sitede yok",
                 detail=f"Aynı bölge ve sektördeki analiz edilmiş rakip sitelerle karşılaştırma: {text}.", severity="medium" if len(gaps) >= 3 else "low", confidence="medium",
                 why="Rakiplerin çoğunun sunduğu içerik/özellikler müşterinin beklentisi haline gelir; eksikliği rakibe geçişi kolaylaştırır.",
                 services=(SVC_WEB, SVC_SEO), category="seo", short="rakiplere göre içerik eksikleri")


def _access_check(signals: WebsiteSignals) -> Check:
    reason = signals.error_reason or "bilinmeyen neden"
    outcome, kind = signals.outcome, signals.failure_kind

    if outcome == "not_a_website":
        return Check(
            key="presence", area="website", label="Kurumsal web sitesi", status="problem",
            value="Kurumsal web sitesi bulunamadı", detail=reason + ".", severity="high", confidence="medium",
            why="Sosyal medya/harita/pazaryeri sayfası, arama motorlarında ve müşteri güveninde kurumsal bir web sitesinin yerini tutmaz.",
            services=(SVC_CORPORATE_SITE,), category="website", source="website_crawl", short="kurumsal web sitesinin bulunmaması",
            needs_verification=True,
        )
    if outcome == "unreachable" and kind in ("dns", "http_404"):
        return Check(
            key="access", area="website", label="Site erişimi", status="problem",
            value="Web sitesi açılmadı", detail=f"Analiz edilemedi — erişim hatası: {reason}.",
            severity="high", confidence="medium",
            why="Adreste açılan bir site yoksa, işletmenin kayıtlardaki web sitesi müşteriye ulaşmaz ve güven kaybettirir.",
            services=(SVC_CORPORATE_SITE, SVC_WEB), category="website", source="website_crawl",
            short="web sitesinin açılmaması", needs_verification=True,
        )
    if outcome == "unreachable" and kind == "http_error":
        return Check(
            key="access", area="website", label="Site erişimi", status="problem",
            value="Web sitesi hata veriyor", detail=f"Analiz edilemedi — erişim hatası: {reason}.",
            severity="high", confidence="medium",
            why="Sunucu hatası veren site ziyaretçi ve arama motoru tarafından erişilemez sayılır.",
            services=(SVC_WEB,), category="website", source="website_crawl", short="web sitesinin hata vermesi",
            needs_verification=True,
        )
    if outcome == "blocked":
        return Check(key="access", area="website", label="Site erişimi", status="unknown",
                     value="Doğrulanamadı — erişim engellendi (bot koruması). Site tarayıcıda elle kontrol edilmeli.",
                     detail=reason, category="website")
    if outcome == "robots_disallowed":
        return Check(key="access", area="website", label="Site erişimi", status="unknown",
                     value="Doğrulanamadı — site robots.txt ile otomatik taramaya izin vermiyor.", detail=reason, category="website")
    return Check(key="access", area="website", label="Site erişimi", status="unknown",
                 value=f"Web sitesi analiz edilemedi — erişim hatası: {reason}", detail=reason, category="website")


def _spam_check(s: WebsiteSignals) -> Check | None:
    if not s.spam_terms:
        return None
    terms = ", ".join(s.spam_terms)
    return Check(
        key="spam_content", area="website", label="Site içeriği güvenliği", status="problem",
        value="Sitede işletmeyle ilgisiz, şüpheli içerik tespit edildi (site ele geçirilmiş olabilir)",
        detail=f'Ana sayfa başlık/metninde şu şüpheli ifadeler bulundu: {terms}. Başlık: "{s.title or "-"}".',
        severity="high", confidence="high",
        why="Ele geçirilmiş/spam içerik gösteren site müşteri güvenini yok eder, Google tarafından cezalandırılır ve tarayıcılarda uyarı çıkarabilir.",
        services=(SVC_WEB, SVC_SEO), category="website", short="sitenin ele geçirilmiş/spam içerik göstermesi",
    )


_GENERIC_NAME_WORDS = {"restoran", "restaurant", "lokantasi", "lokanta", "otel", "hotel", "eczanesi", "eczane", "klinigi", "klinik", "poliklinigi", "kafe", "cafe",
                       "ltd", "sti", "limited", "sirketi", "anonim", "san", "tic", "ve", "dis", "hekimi", "dr", "uzm", "insaat", "turizm", "gida", "ticaret", "sanayi"}


def _brand_check(ctx: AnalysisContext, s: WebsiteSignals) -> Check | None:
    """İşletme adı sitede hiç geçmiyorsa: adres başka bir işletmeye/alakasız bir siteye ait olabilir."""
    tokens = [t for t in fold(ctx.business_name).split() if len(t) >= 4 and t not in _GENERIC_NAME_WORDS]
    if not tokens or s.js_rendered_hint:
        return None
    haystack = fold(" ".join(filter(None, [s.title, s.meta_description, " ".join(s.h1_texts), s.text_excerpt])))
    if any(t in haystack for t in tokens):
        return None
    return Check(
        key="brand_match", area="website", label="İşletme adı uyumu", status="problem",
        value="İşletme adı sitede geçmiyor — adres başka bir siteye ait olabilir",
        detail=f'"{ctx.business_name}" ifadesi ana sayfanın başlığında, açıklamasında ve metninde bulunamadı; kayıtlı web sitesi adresi doğru olmayabilir.',
        severity="medium", confidence="medium",
        why="Kayıtlı adres işletmenin gerçek sitesi değilse müşteri yanlış yere yönlenir; doğru ve kurumsal bir site gerekir.",
        services=(SVC_WEB,), category="website", short="kayıtlı web sitesinin işletmeyle uyumsuz görünmesi", needs_verification=True,
    )


def _https_check(s: WebsiteSignals) -> Check:
    if s.ssl_error:
        return Check(
            key="https", area="website", label="HTTPS / güvenlik", status="problem",
            value="SSL sertifikası geçersiz", detail=f"{s.final_url} adresinin SSL sertifikası geçersiz veya süresi dolmuş.",
            severity="high", confidence="high",
            why="Tarayıcılar 'güvenli değil' uyarısı gösterir; ziyaretçilerin önemli kısmı siteyi terk eder ve Google güvensiz siteleri geri sıralar.",
            services=(SVC_WEB,), category="website", short="SSL sertifika sorunu",
        )
    if not s.https_enabled:
        return Check(
            key="https", area="website", label="HTTPS / güvenlik", status="problem",
            value="Site HTTPS kullanmıyor", detail=f"{s.final_url} adresi güvenli (HTTPS) bağlantıyla açılmıyor.",
            severity="medium", confidence="high",
            why="Tarayıcılar 'güvenli değil' uyarısı gösterebilir, ziyaretçi güveni ve Google sıralaması olumsuz etkilenir.",
            services=(SVC_WEB,), category="website", short="HTTPS eksikliği",
        )
    return Check(key="https", area="website", label="HTTPS / güvenlik", status="ok", value="HTTPS kullanılıyor", category="website")


def _mobile_check(s: WebsiteSignals) -> Check:
    if s.viewport_ok:
        return Check(key="mobile", area="website", label="Mobil uyumluluk", status="ok",
                     value="Mobil uyumluluk etiketi (viewport) var — gerçek cihaz testi yapılmadı", category="website")
    return Check(
        key="mobile", area="website", label="Mobil uyumluluk", status="problem",
        value="Mobil uyumluluk etiketi (viewport) yok",
        detail="Sayfada 'viewport' (width=device-width) etiketi bulunamadı; site telefonlarda masaüstü görünümüyle küçük açılıyor olabilir. "
        "(Not: yalnızca bu etiket kontrol edildi, gerçek cihaz testi yapılmadı.)",
        severity="high", confidence="medium",
        why="Aramaların çoğu telefondan yapılır; mobilde düzgün görünmeyen site ziyaretçiyi iletişime geçmeden kaybettirir.",
        services=(SVC_WEB,), category="website", short="mobil uyumluluk eksikliği",
    )


def _speed_check(s: WebsiteSignals) -> Check:
    ps = s.pagespeed
    if ps and ps.get("performance_score") is not None:
        score = ps["performance_score"]
        if score < 50:
            return Check(key="speed", area="website", label="Sayfa hızı (Google PageSpeed, mobil)", status="problem",
                         value=f"Mobil performans puanı {score}/100 (düşük)", detail=f"Google PageSpeed mobil performans puanı {score}/100.",
                         severity="high", confidence="high",
                         why="Yavaş açılan site, ziyaretçinin siteyi terk etme olasılığını artırır ve Google sıralamasını düşürür.",
                         services=(SVC_WEB,), category="website", source="pagespeed", short="düşük sayfa hızı")
        if score < 90:
            return Check(key="speed", area="website", label="Sayfa hızı (Google PageSpeed, mobil)", status="problem",
                         value=f"Mobil performans puanı {score}/100 (geliştirilebilir)", detail=f"Google PageSpeed mobil performans puanı {score}/100.",
                         severity="low", confidence="high",
                         why="Hız iyileştirmeleri dönüşümü ve arama sıralamasını destekler.",
                         services=(SVC_WEB,), category="website", source="pagespeed", short="sayfa hızı")
        return Check(key="speed", area="website", label="Sayfa hızı (Google PageSpeed, mobil)", status="ok",
                     value=f"Mobil performans puanı {score}/100", category="website", source="pagespeed")

    # PageSpeed yok: kendi ölçümümüz — yaklaşık gösterge, tam tarayıcı ölçümü değil.
    if s.response_ms is None:
        return Check(key="speed", area="website", label="Sayfa hızı", status="unknown", value="Doğrulanamadı", category="website")
    seconds = s.response_ms / 1000
    kb = round((s.html_bytes or 0) / 1024)
    approx = f"Ana sayfa {seconds:.1f} sn'de alındı ({kb} KB HTML) — yaklaşık ölçüm, tarayıcı render süresi dahil değil"
    if s.response_ms >= SLOW_RESPONSE_MS:
        return Check(key="speed", area="website", label="Sayfa hızı", status="problem", value=f"Yavaş: {seconds:.1f} sn",
                     detail=approx + ".", severity="medium", confidence="medium",
                     why="Yavaş açılan site ziyaretçi kaybettirir ve Google sıralamasını olumsuz etkiler.",
                     services=(SVC_WEB,), category="website", short="yavaş açılan sayfa")
    return Check(key="speed", area="website", label="Sayfa hızı", status="ok", value=approx, category="website")


def _title_check(s: WebsiteSignals) -> Check:
    title = s.title
    if not title:
        return Check(key="title", area="website", label="Sayfa başlığı (title)", status="problem", value="Title etiketi yok",
                     detail="Ana sayfada dolu bir <title> etiketi bulunamadı.", severity="high", confidence="high",
                     why="Google sonuçlarında ve tarayıcı sekmesinde işletme adı yerine boş/otomatik başlık görünür; arama görünürlüğü zayıflar.",
                     services=(SVC_SEO,), category="seo", short="title etiketinin olmaması")
    folded = fold(title)
    generic = folded in GENERIC_TITLES or (folded.startswith("ana sayfa") and len(folded.split()) <= 3)
    if generic:
        return Check(key="title", area="website", label="Sayfa başlığı (title)", status="problem",
                     value=f'Title etiketi yetersiz: "{title}"', detail=f'Title etiketi genel/varsayılan bir ifade: "{title}" — işletme adı, hizmet ve şehir bilgisi yok.',
                     severity="medium", confidence="high",
                     why="Arama sonuçlarında ilk görünen satır budur; genel bir başlık tıklamayı ve sıralamayı düşürür.",
                     services=(SVC_SEO,), category="seo", short="yetersiz title etiketi")
    if len(title) < 15:
        return Check(key="title", area="website", label="Sayfa başlığı (title)", status="problem",
                     value=f'Title çok kısa: "{title}" ({len(title)} karakter)', detail=f'Title etiketi yalnızca {len(title)} karakter: "{title}".',
                     severity="low", confidence="high",
                     why="Kısa başlık, arama sonucunda hizmet ve konum bilgisini aktaramaz.",
                     services=(SVC_SEO,), category="seo", short="kısa title etiketi")
    if len(title) > 70:
        return Check(key="title", area="website", label="Sayfa başlığı (title)", status="problem",
                     value=f"Title çok uzun ({len(title)} karakter)", detail=f'Title {len(title)} karakter; arama sonuçlarında kesilir: "{title}".',
                     severity="low", confidence="high", why="Uzun başlıklar Google sonuçlarında kesilir, mesaj yarım kalır.",
                     services=(SVC_SEO,), category="seo", short="çok uzun title etiketi")
    return Check(key="title", area="website", label="Sayfa başlığı (title)", status="ok", value=f'"{title}" ({len(title)} karakter)', category="seo")


def _title_keyword_check(ctx: AnalysisContext, s: WebsiteSignals) -> Check:
    if not s.title:
        return Check(key="title_keywords", area="website", label="Başlıkta hizmet ve şehir", status="unknown", value="Doğrulanamadı (title yok)", category="seo")
    has_service = _mentions_any(s.title, ctx.sector_phrases)
    has_place = _mentions_any(s.title, ctx.place_names)
    if has_service and has_place:
        return Check(key="title_keywords", area="website", label="Başlıkta hizmet ve şehir", status="ok",
                     value="Title'da hizmet ve şehir bilgisi var", category="seo")
    missing = []
    if not has_service:
        missing.append("ana hizmet")
    if not has_place:
        missing.append("şehir/ilçe")
    joined = " ve ".join(missing)
    return Check(
        key="title_keywords", area="website", label="Başlıkta hizmet ve şehir", status="problem",
        value=f"Title etiketi yetersiz: {joined} bilgisi bulunmuyor",
        detail=f'Title: "{s.title}" — {joined} ifadesi geçmiyor (aranan: "{ctx.main_phrase}" / "{ctx.place}").',
        severity="medium" if not (has_service or has_place) else "low", confidence="high",
        why="Kişiler '{} {}' gibi aramalar yapar; başlıkta bu ifadeler yoksa Google siteyi bu aramalarla eşleştirmekte zorlanır.".format(ctx.main_phrase, ctx.place).strip(),
        services=(SVC_SEO,) if has_place else (SVC_SEO, SVC_LOCAL_SEO), category="seo", short="title'da hizmet/şehir bilgisinin eksik olması",
    )


def _meta_description_check(s: WebsiteSignals) -> Check:
    desc = s.meta_description
    if not desc:
        return Check(key="meta_description", area="website", label="Meta açıklama (description)", status="problem",
                     value="Meta description yok", detail="Ana sayfada meta description etiketi bulunamadı.",
                     severity="medium", confidence="high",
                     why="Arama sonucundaki açıklama metni Google tarafından rastgele seçilir; tıklama oranı ve mesaj kontrolü kaybolur.",
                     services=(SVC_SEO,), category="seo", short="meta description eksikliği")
    if len(desc) < 70:
        return Check(key="meta_description", area="website", label="Meta açıklama (description)", status="problem",
                     value=f"Meta description çok kısa ({len(desc)} karakter)", detail=f'Meta description: "{desc}" ({len(desc)} karakter).',
                     severity="low", confidence="high", why="Kısa açıklama, arama sonucunda hizmeti ve avantajları anlatmaya yetmez.",
                     services=(SVC_SEO,), category="seo", short="kısa meta description")
    if len(desc) > 180:
        return Check(key="meta_description", area="website", label="Meta açıklama (description)", status="problem",
                     value=f"Meta description çok uzun ({len(desc)} karakter)", detail=f"Meta description {len(desc)} karakter; Google sonuçlarında kesilir.",
                     severity="low", confidence="high", why="Uzun açıklama arama sonucunda kesilir.",
                     services=(SVC_SEO,), category="seo", short="uzun meta description")
    return Check(key="meta_description", area="website", label="Meta açıklama (description)", status="ok", value=f"Var ({len(desc)} karakter)", category="seo")


_JS_NOTE = "Doğrulanamadı — sayfa içeriği JavaScript ile oluşturuluyor olabilir (statik HTML'de ölçülemedi)"


def _h1_check(s: WebsiteSignals) -> Check:
    if not s.h1_texts and s.js_rendered_hint:
        return Check(key="h1", area="website", label="Ana başlık (H1)", status="unknown", value=_JS_NOTE, category="seo")
    if not s.h1_texts:
        return Check(key="h1", area="website", label="Ana başlık (H1)", status="problem", value="H1 başlığı yok",
                     detail="Ana sayfada <h1> etiketi bulunamadı.", severity="medium", confidence="high",
                     why="Arama motorları sayfanın ana konusunu H1'den anlar; yoksa konu belirsizleşir.",
                     services=(SVC_SEO,), category="seo", short="H1 başlığının olmaması")
    return Check(key="h1", area="website", label="Ana başlık (H1)", status="ok", value=f'"{s.h1_texts[0][:80]}"', category="seo")


def _heading_structure_check(s: WebsiteSignals) -> Check:
    if s.js_rendered_hint:
        return Check(key="heading_structure", area="website", label="Başlık yapısı (H2/H3)", status="unknown", value=_JS_NOTE, category="seo")
    h2, words = s.h2_count or 0, s.word_count or 0
    if h2 == 0 and words >= 150:
        return Check(key="heading_structure", area="website", label="Başlık yapısı (H2/H3)", status="problem",
                     value="Alt başlık (H2) yok", detail=f"Sayfada {words} kelimelik içerik var ancak hiç H2 alt başlığı yok.",
                     severity="low", confidence="high", why="Alt başlıklar içeriği hem ziyaretçi hem arama motoru için taranabilir kılar.",
                     services=(SVC_SEO,), category="seo", short="başlık yapısının zayıflığı")
    return Check(key="heading_structure", area="website", label="Başlık yapısı (H2/H3)", status="ok",
                 value=f"{h2} adet H2, {s.h3_count or 0} adet H3", category="seo")


def _local_seo_check(ctx: AnalysisContext, s: WebsiteSignals, head_text: str) -> Check:
    places = ctx.place_names
    if not places:
        return Check(key="local_seo", area="website", label="Yerel SEO (şehir/ilçe)", status="unknown", value="Doğrulanamadı", category="seo")
    in_head = _mentions_any(head_text, places)
    in_body = _mentions_any(s.text_excerpt, places)
    if in_head:
        return Check(key="local_seo", area="website", label="Yerel SEO (şehir/ilçe)", status="ok",
                     value=f"{ctx.place} adı başlık/açıklamada geçiyor", category="seo")
    if not in_body and s.js_rendered_hint:
        return Check(key="local_seo", area="website", label="Yerel SEO (şehir/ilçe)", status="unknown", value=_JS_NOTE, category="seo")
    if in_body:
        return Check(key="local_seo", area="website", label="Yerel SEO (şehir/ilçe)", status="problem",
                     value=f"{ctx.place} adı yalnızca sayfa metninde geçiyor",
                     detail=f'"{ctx.place}" ifadesi title, H1 ve meta description\'da yok; yalnızca gövde metninde var.',
                     severity="low", confidence="medium",
                     why="Yerel aramalarda şehir/ilçe adının başlık ve açıklamada da geçmesi sıralamayı güçlendirir.",
                     services=(SVC_LOCAL_SEO,), category="seo", short="yerel SEO eksikliği")
    return Check(key="local_seo", area="website", label="Yerel SEO (şehir/ilçe)", status="problem",
                 value=f"{ctx.place} adı sitede belirgin şekilde geçmiyor",
                 detail=f'"{ctx.place}" ifadesi title, H1, meta description ve ana sayfa metninin başında bulunamadı.',
                 severity="medium", confidence="medium",
                 why=f"'{ctx.main_phrase} {ctx.place}' gibi yerel aramalarda site Google'a bölgesel olarak ilgili görünmez.",
                 services=(SVC_LOCAL_SEO, SVC_SEO), category="seo", short="yerel SEO eksikliği")


def _content_volume_check(s: WebsiteSignals) -> Check:
    words = s.word_count or 0
    if words < 150 and s.js_rendered_hint:
        return Check(key="content_volume", area="website", label="İçerik miktarı", status="unknown", value=_JS_NOTE, category="seo")
    if words < 150:
        return Check(key="content_volume", area="website", label="İçerik miktarı", status="problem",
                     value=f"Ana sayfada çok az metin ({words} kelime)", detail=f"Ana sayfada yalnızca {words} kelime metin var.",
                     severity="medium", confidence="medium",
                     why="Az içerik, Google'ın siteyi hizmet/bölge aramalarıyla eşleştirmesini zorlaştırır.",
                     services=(SVC_SEO,), category="seo", short="az içerik")
    return Check(key="content_volume", area="website", label="İçerik miktarı", status="ok", value=f"{words} kelime", category="seo")


def _schema_check(s: WebsiteSignals) -> Check:
    local_types = {t for t in s.schema_types if any(k in t for k in ("LocalBusiness", "Organization", "Store", "Restaurant", "Dentist", "Hotel", "Physician", "MedicalBusiness", "HealthAndBeautyBusiness", "AutoRepair"))}
    if local_types:
        return Check(key="schema", area="website", label="Yapılandırılmış veri (schema)", status="ok",
                     value=", ".join(sorted(local_types)), category="seo")
    return Check(key="schema", area="website", label="Yapılandırılmış veri (schema)", status="problem",
                 value="İşletme (LocalBusiness) schema verisi yok",
                 detail="Sayfada LocalBusiness/Organization türünde yapılandırılmış veri (schema.org) bulunamadı.",
                 severity="low", confidence="medium",
                 why="Google, adres/saat/puan gibi işletme bilgilerini arama sonucunda zenginleştirmek için bu veriyi kullanır.",
                 services=(SVC_SEO,), category="seo", short="schema (yapılandırılmış veri) eksikliği")


def _indexing_check(s: WebsiteSignals) -> Check:
    if s.noindex:
        return Check(key="indexing", area="website", label="Google'da indekslenme", status="problem",
                     value="Sayfa Google'dan gizlenmiş (noindex)", detail="Ana sayfada robots meta etiketi 'noindex' içeriyor.",
                     severity="high", confidence="high",
                     why="Bu etiket sayfanın Google sonuçlarında hiç çıkmamasına neden olur.",
                     services=(SVC_SEO,), category="seo", short="sitenin Google'dan gizlenmesi (noindex)")
    return Check(key="indexing", area="website", label="Google'da indekslenme", status="ok", value="Engelleyen bir etiket yok", category="seo")


def _sitemap_check(s: WebsiteSignals) -> Check:
    if s.sitemap_present is None:
        return Check(key="sitemap", area="website", label="Site haritası (sitemap.xml)", status="unknown", value="Doğrulanamadı", category="seo")
    if not s.sitemap_present:
        return Check(key="sitemap", area="website", label="Site haritası (sitemap.xml)", status="problem", value="sitemap.xml bulunamadı",
                     detail="Sitede /sitemap.xml adresi açılmıyor.", severity="low", confidence="medium",
                     why="Site haritası Google'ın tüm sayfaları keşfetmesine yardımcı olur.",
                     services=(SVC_SEO,), category="seo", short="site haritası eksikliği")
    return Check(key="sitemap", area="website", label="Site haritası (sitemap.xml)", status="ok", value="Var", category="seo")


def _phone_click_check(s: WebsiteSignals) -> Check:
    if s.tel_link_present:
        return Check(key="tel_link", area="website", label="Tıklanabilir telefon", status="ok", value="Telefon bağlantısı (tel:) var", category="website")
    if s.phone_in_text:
        return Check(key="tel_link", area="website", label="Tıklanabilir telefon", status="problem",
                     value="Telefon numarası var ama tıklanabilir değil",
                     detail="Sayfada telefon numarası görünüyor ancak tel: bağlantısı yok; mobilde tek dokunuşla aranamaz.",
                     severity="medium", confidence="medium",
                     why="Mobil ziyaretçi numarayı elle çevirmek zorunda kalır, arama yapmadan vazgeçebilir.",
                     services=(SVC_WEB,), category="website", short="tıklanabilir telefon bağlantısının olmaması")
    return Check(key="tel_link", area="website", label="Tıklanabilir telefon", status="problem",
                 value="Ana sayfada telefon numarası bulunamadı", detail="Ana sayfada ne telefon numarası ne de tel: bağlantısı tespit edildi.",
                 severity="medium", confidence="medium",
                 why="Ziyaretçi işletmeye ulaşmanın yolunu bulamazsa müşteri olmadan ayrılır.",
                 services=(SVC_WEB,), category="website", short="telefon bilgisinin bulunmaması")


def _whatsapp_check(s: WebsiteSignals) -> Check:
    if s.whatsapp_link_present:
        return Check(key="whatsapp", area="website", label="WhatsApp bağlantısı", status="ok", value="Var", category="website")
    return Check(key="whatsapp", area="website", label="WhatsApp bağlantısı", status="problem", value="WhatsApp bağlantısı yok",
                 detail="Sayfada wa.me / WhatsApp bağlantısı tespit edilmedi.", severity="low", confidence="high",
                 why="Türkiye'de müşteri iletişiminin önemli bir kısmı WhatsApp üzerinden yürür.",
                 services=(SVC_WEB,), category="website", short="WhatsApp bağlantısının olmaması")


def _maps_check(ctx: AnalysisContext, s: WebsiteSignals) -> Check:
    if s.maps_link_present:
        return Check(key="maps_link", area="website", label="Google Haritalar bağlantısı", status="ok", value="Harita/konum bağlantısı var", category="website")
    return Check(key="maps_link", area="website", label="Google Haritalar bağlantısı", status="problem", value="Harita/konum bağlantısı yok",
                 detail="Ana sayfada Google Haritalar bağlantısı veya gömülü harita tespit edilmedi.",
                 severity="low", confidence="medium",
                 why="Fiziksel mekânı olan işletmede ziyaretçinin yol tarifi alabilmesi müşteriyi kapıya getirir.",
                 services=(SVC_WEB,), category="website", short="konum/harita bağlantısının olmaması")


def _conversion_check(s: WebsiteSignals) -> Check:
    points = {
        "telefon": s.tel_link_present,
        "telefon (yalnızca düz metin)": s.phone_in_text,
        "WhatsApp": s.whatsapp_link_present,
        "iletişim formu": s.form_present,
        "randevu/rezervasyon bağlantısı": s.has_appointment_link,
        "e-posta": s.email_in_text,
    }
    present = [name for name, flag in points.items() if flag]
    if not present:
        return Check(key="conversion", area="website", label="Dönüşüm / iletişim alma noktaları", status="problem",
                     value="Ziyaretçiyi müşteriye çeviren hiçbir iletişim noktası yok",
                     detail="Ana sayfada telefon numarası/bağlantısı, WhatsApp, form, randevu/rezervasyon bağlantısı veya e-posta tespit edilmedi.",
                     severity="high", confidence="medium",
                     why="Ziyaretçinin tek tıkla ulaşabileceği bir iletişim noktası yoksa siteye gelen trafik müşteriye dönüşmez.",
                     services=(SVC_WEB,), category="website", short="iletişim/dönüşüm noktalarının olmaması")
    if len(present) == 1:
        return Check(key="conversion", area="website", label="Dönüşüm / iletişim alma noktaları", status="problem",
                     value=f"Tek iletişim noktası var ({present[0]})", detail=f"Ana sayfada yalnızca {present[0]} tespit edildi.",
                     severity="low", confidence="medium", why="Tek bir iletişim yolu, farklı tercih eden ziyaretçileri kaybettirir.",
                     services=(SVC_WEB,), category="website", short="sınırlı iletişim noktaları")
    return Check(key="conversion", area="website", label="Dönüşüm / iletişim alma noktaları", status="ok", value=", ".join(present), category="website")


def _booking_check(ctx: AnalysisContext, s: WebsiteSignals) -> Check | None:
    if not (ctx.profile.appointment_based or ctx.profile.reservation_based):
        return None
    word = "rezervasyon" if ctx.profile.reservation_based else "randevu"
    if s.has_appointment_link or s.form_present:
        return Check(key="booking", area="website", label=f"Online {word}", status="ok", value=f"{word.capitalize()} bağlantısı/formu var", category="website")
    return Check(key="booking", area="website", label=f"Online {word}", status="problem", value=f"Online {word} imkânı yok",
                 detail=f"Sayfada {word} bağlantısı veya formu tespit edilmedi.",
                 severity="medium" if ctx.profile.booking_important else "low", confidence="medium",
                 why=f"Bu sektörde müşteriler {word} yapmak ister; online {word} olmayan siteler telefona bağımlı kalır ve mesai dışı talebi kaçırır.",
                 services=(SVC_WEB,), category="website", short=f"online {word} eksikliği")


def _services_page_check(s: WebsiteSignals) -> Check:
    if s.has_services_page:
        return Check(key="services_page", area="website", label="Hizmet/ürün sayfaları", status="ok", value="Menüde hizmet/ürün bağlantısı var", category="website")
    return Check(key="services_page", area="website", label="Hizmet/ürün sayfaları", status="problem",
                 value="Hizmetler bölümü/sayfası bulunamadı", detail="Ana sayfa bağlantılarında hizmet/ürün/menü sayfasına giden bir bağlantı tespit edilmedi.",
                 severity="medium", confidence="medium",
                 why="Her hizmet için ayrı sayfa, hem ziyaretçiye net bilgi verir hem de hizmete özel aramalarda sıralama şansı yaratır.",
                 services=(SVC_WEB, SVC_SEO), category="website", short="hizmetler bölümünün eksikliği")


def _about_check(s: WebsiteSignals) -> Check:
    if s.has_about_page:
        return Check(key="about", area="website", label="Hakkımızda", status="ok", value="Var", category="website")
    return Check(key="about", area="website", label="Hakkımızda", status="problem", value="Hakkımızda/kurumsal sayfa bulunamadı",
                 detail="Menüde hakkımızda/kurumsal bağlantısı tespit edilmedi.", severity="low", confidence="medium",
                 why="Hakkımızda sayfası güven ve marka algısı için ziyaretçinin ilk baktığı yerlerden biridir.",
                 services=(SVC_WEB,), category="website", short="hakkımızda sayfasının eksikliği")


def _references_check(s: WebsiteSignals) -> Check:
    if s.has_references_page:
        return Check(key="references", area="website", label="Referanslar / galeri", status="ok", value="Var", category="website")
    return Check(key="references", area="website", label="Referanslar / galeri", status="problem", value="Referans/galeri/proje sayfası bulunamadı",
                 detail="Menüde referans, galeri veya proje bağlantısı tespit edilmedi.", severity="low", confidence="low",
                 why="Önceki iş/müşteri örnekleri karar verme sürecinde güven sağlar.",
                 services=(SVC_WEB,), category="website", short="referans/galeri eksikliği")


def _blog_check(s: WebsiteSignals) -> Check:
    if s.has_blog:
        return Check(key="blog", area="website", label="Blog / içerik", status="ok", value="Var", category="seo")
    return Check(key="blog", area="website", label="Blog / içerik", status="problem", value="Blog/haber bölümü bulunamadı",
                 detail="Menüde blog, makale veya haber bağlantısı tespit edilmedi.", severity="low", confidence="low",
                 why="Düzenli içerik, siteye organik (Google'dan gelen) ziyaretçi çekmenin en güçlü yollarından biridir.",
                 services=(SVC_SEO,), category="seo", short="blog/içerik eksikliği")


def _images_check(s: WebsiteSignals) -> Check:
    total, missing = s.images_total or 0, s.images_missing_alt or 0
    if total == 0:
        return Check(key="images", area="website", label="Görseller ve alt metinleri", status="problem", value="Ana sayfada görsel yok",
                     detail="Ana sayfada <img> görseli tespit edilmedi (arka plan görselleri sayılmaz).", severity="low", confidence="low",
                     why="Görselsiz site profesyonellik algısını düşürür.", services=(SVC_GRAPHIC,), category="website", short="görsel eksikliği")
    if total >= 5 and missing / total > 0.5:
        return Check(key="images", area="website", label="Görseller ve alt metinleri", status="problem",
                     value=f"{total} görselin {missing}'inde alt metni yok", detail=f"Ana sayfadaki {total} görselin {missing} tanesinde alt (açıklama) metni boş.",
                     severity="low", confidence="high",
                     why="Alt metin yoksa Google görseli anlayamaz (görsel arama kaybı) ve ekran okuyucu kullanıcıları içeriği alamaz.",
                     services=(SVC_SEO,), category="seo", short="görsel alt metinlerinin eksikliği")
    return Check(key="images", area="website", label="Görseller ve alt metinleri", status="ok", value=f"{total} görsel, {missing} tanesinde alt metni yok", category="website")


def _broken_links_check(s: WebsiteSignals) -> Check:
    if not s.links_checked:
        return Check(key="broken_links", area="website", label="Kırık bağlantılar", status="unknown", value="Doğrulanamadı (kontrol edilecek iç bağlantı bulunamadı)", category="website")
    if s.broken_links:
        sample = ", ".join(f"{b['url']} (HTTP {b['status']})" for b in s.broken_links[:3])
        return Check(key="broken_links", area="website", label="Kırık bağlantılar", status="problem",
                     value=f"{len(s.broken_links)} kırık bağlantı", detail=f"Kontrol edilen {s.links_checked} iç bağlantıdan {len(s.broken_links)} tanesi açılmıyor: {sample}.",
                     severity="medium", confidence="high",
                     why="Kırık bağlantılar ziyaretçiyi hayal kırıklığına uğratır ve Google'ın site kalitesi değerlendirmesini düşürür.",
                     services=(SVC_WEB,), category="website", short="kırık bağlantılar")
    return Check(key="broken_links", area="website", label="Kırık bağlantılar", status="ok",
                 value=f"Kontrol edilen {s.links_checked} iç bağlantıda kırık yok", category="website")


def _social_link_check(s: WebsiteSignals) -> Check:
    networks = [n for n in ("instagram", "facebook") if s.social_links.get(n)]
    if networks:
        return Check(key="social_links", area="website", label="Sosyal medya bağlantıları", status="ok", value=", ".join(n.capitalize() for n in networks), category="social")
    return Check(key="social_links", area="website", label="Sosyal medya bağlantıları", status="problem",
                 value="Sitede Instagram/Facebook bağlantısı yok",
                 detail="Ana sayfada Instagram veya Facebook bağlantısı tespit edilmedi (hesabın hiç olmadığı anlamına gelmez).",
                 severity="low", confidence="low",
                 why="Site ziyaretçisi sosyal medya hesabına yönlendirilemez; marka takibi ve güven zayıflar.",
                 services=(SVC_SOCIAL,), category="social", short="sosyal medya bağlantısının olmaması")


def _freshness_check(ctx: AnalysisContext, s: WebsiteSignals) -> Check:
    if not s.copyright_year:
        return Check(key="freshness", area="website", label="Site güncelliği", status="unknown", value="Doğrulanamadı (telif yılı bulunamadı)", category="website")
    age = ctx.now.year - s.copyright_year
    if age >= STALE_COPYRIGHT_YEARS:
        return Check(key="freshness", area="website", label="Site güncelliği", status="problem",
                     value=f"Alt bilgide © {s.copyright_year} yazıyor", detail=f"Sitenin alt bilgisindeki son telif yılı {s.copyright_year} ({age} yıl önce) — site uzun süredir güncellenmemiş olabilir.",
                     severity="low", confidence="medium",
                     why="Güncel görünmeyen site güven kaybettirir ve eski teknolojiyle mobil/hız sorunları yaşatır.",
                     services=(SVC_WEB,), category="website", short="sitenin güncel görünmemesi")
    return Check(key="freshness", area="website", label="Site güncelliği", status="ok", value=f"Son telif yılı {s.copyright_year}", category="website")


def _ecommerce_check(s: WebsiteSignals) -> Check:
    if s.has_shop_signals:
        return Check(key="ecommerce", area="website", label="Online satış", status="ok", value="Sepet/online satış işaretleri var", category="website")
    return Check(key="ecommerce", area="website", label="Online satış", status="problem", value="Online satış altyapısı tespit edilmedi",
                 detail="Bu sektör ürün satıyor ancak sitede sepet, 'sepete ekle' veya e-ticaret altyapısı işareti bulunamadı.",
                 severity="medium", confidence="medium",
                 why="Mağaza dışındaki (online) talep kaçırılır; müşteri ürünü başka bir e-ticaret sitesinden alır.",
                 services=(SVC_ECOM,), category="website", short="online satış altyapısının olmaması")


# ============================================================================ GOOGLE İŞLETME PROFİLİ
_GENERIC_GOOGLE_TYPES = {"point_of_interest", "establishment", "food", "health", "store", "premise", "service", "finance", "place_of_worship"}
_GBP_UNAVAILABLE = "Doğrulanamadı"


def _unknown(key: str, label: str, value: str = _GBP_UNAVAILABLE, detail: str = "") -> Check:
    return Check(key=key, area="gbp", label=label, status="unknown", value=value, detail=detail, category="gbp", source="places")


def build_gbp_checks(ctx: AnalysisContext, business) -> list[Check]:
    """Google İşletme Profili kontrolleri. Veri kaynağı Google değilse (OSM) Google'a ait hiçbir alan tahmin edilmez."""
    if ctx.google_profile is not None:
        return _gbp_checks_from_profile(ctx, business, ctx.google_profile)
    if not ctx.is_google_data:
        return _gbp_checks_without_google(ctx, business)

    checks: list[Check] = []
    profile = business.source_profile or {}
    types = profile.get("types") or profile.get("categories") or []

    # ---- işletme durumu
    status = profile.get("business_status")
    if status in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        text = "Kalıcı olarak kapalı" if status == "CLOSED_PERMANENTLY" else "Geçici olarak kapalı"
        checks.append(Check(key="business_status", area="gbp", label="İşletme durumu", status="problem", value=f"Google'da '{text}' görünüyor",
                            detail=f"Google İşletme Profili durumu: {text}.", severity="none", confidence="high",
                            why="Kapalı görünen işletme satış hedefi değildir; bilgiyi doğrulayın.", category="gbp", source="places", short="kapalı görünmesi"))

    # ---- birincil kategori
    label = business.category_label
    expected = ctx.profile.google_types
    primary_type = profile.get("primary_type")
    if not label:
        checks.append(Check(key="primary_category", area="gbp", label="Birincil kategori", status="problem", value="Birincil kategori belirlenmemiş",
                            detail="Google profilinde birincil kategori bilgisi görünmüyor.", severity="medium", confidence="medium",
                            why="Kategori, Google Haritalar'da hangi aramalarda görüneceğinizi belirleyen en önemli alandır.",
                            services=(SVC_GBP,), category="gbp", source="places", short="birincil kategori eksikliği"))
    elif expected and primary_type and primary_type not in expected and not (set(types) & expected):
        checks.append(Check(key="primary_category", area="gbp", label="Birincil kategori", status="problem",
                            value=f'Kategori "{label}" sektörle uyumsuz görünüyor',
                            detail=f'Google birincil kategorisi "{label}"; "{ctx.sector_name}" sektörü için beklenen kategorilerle eşleşmiyor.',
                            severity="medium", confidence="medium",
                            why="Yanlış kategori, doğru müşterilerin sizi Google Haritalar aramalarında görmesini engeller.",
                            services=(SVC_GBP,), category="gbp", source="places", short="kategori uyumsuzluğu"))
    else:
        checks.append(Check(key="primary_category", area="gbp", label="Birincil kategori", status="ok", value=label, category="gbp", source="places"))

    # ---- ek kategoriler
    specific = [t for t in types if t not in _GENERIC_GOOGLE_TYPES and t != primary_type]
    if types:
        if not specific:
            checks.append(Check(key="extra_categories", area="gbp", label="Ek kategoriler", status="problem", value="Ek kategori görünmüyor",
                                detail="Google profilinde birincil kategorinin dışında özel bir ek kategori tespit edilmedi.",
                                severity="low", confidence="low",
                                why="Ek kategoriler, işletmenin daha fazla arama türünde görünmesini sağlar.",
                                services=(SVC_GBP,), category="gbp", source="places", short="ek kategori eksikliği"))
        else:
            checks.append(Check(key="extra_categories", area="gbp", label="Ek kategoriler", status="ok", value=f"{len(specific)} ek kategori", category="gbp", source="places"))
    else:
        checks.append(_unknown("extra_categories", "Ek kategoriler"))

    # ---- Google'ın API'de vermediği alanlar
    reason = "Google bu bilgiyi API'de vermiyor; Google Haritalar'da profili açarak elle kontrol edin."
    checks.append(_unknown("description", "İşletme açıklaması", detail=reason))
    checks.append(_unknown("services_list", "Hizmetler / ürünler bölümü", detail=reason))

    # ---- iletişim alanları
    checks.append(_gbp_field("phone", "Telefon", business.phone, "Telefon numarası yok", "Profilde telefon yoksa arayan müşteri işletmeye tek dokunuşla ulaşamaz.", "medium"))
    checks.append(
        _gbp_field(
            "website", "Web sitesi", business.website, "Web sitesi yok",
            "Profildeki web sitesi bağlantısı Google'dan gelen ziyaretçinin ilk durağıdır.", "high",
            services=(SVC_CORPORATE_SITE, SVC_GBP),
        )
    )
    checks.append(_gbp_field("hours", "Çalışma saatleri", business.opening_hours, "Çalışma saatleri girilmemiş", "Saat bilgisi olmayan profil 'açık mı?' sorusunu cevaplayamaz ve daha az öne çıkar.", "medium"))

    # ---- fotoğraf
    photo_count = business.photo_count
    capped = bool(profile.get("photos_capped"))
    if photo_count is None:
        checks.append(_unknown("photos", "Fotoğraflar"))
    elif photo_count == 0:
        checks.append(Check(key="photos", area="gbp", label="Fotoğraflar", status="problem", value="Profilde fotoğraf yok", detail="Google profilinde hiç fotoğraf görünmüyor.",
                            severity="high", confidence="high", why="Fotoğrafsız profiller tıklama ve arama dönüşümünde belirgin şekilde geride kalır.",
                            services=(SVC_GBP, SVC_GRAPHIC), category="gbp", source="places", short="fotoğraf eksikliği"))
    elif photo_count < LOW_PHOTO_THRESHOLD and not capped:
        checks.append(Check(key="photos", area="gbp", label="Fotoğraflar", status="problem", value=f"Yalnızca {photo_count} fotoğraf var",
                            detail=f"Google profilinde {photo_count} fotoğraf görünüyor (eşik: {LOW_PHOTO_THRESHOLD}).", severity="medium", confidence="high",
                            why="Az fotoğraf, işletmenin Google Haritalar'da daha az ilgi çekici ve güvenilir görünmesine yol açar.",
                            services=(SVC_GBP, SVC_GRAPHIC), category="gbp", source="places", short="az fotoğraf"))
    else:
        shown = f"{photo_count}+" if capped else str(photo_count)
        checks.append(Check(key="photos", area="gbp", label="Fotoğraflar", status="ok", value=f"{shown} fotoğraf", category="gbp", source="places"))
    checks.append(_unknown("last_photo", "Son fotoğraf tarihi", detail=reason))

    # ---- yorumlar
    count, rating = business.google_review_count, business.google_rating
    if count is None:
        checks.append(_unknown("review_count", "Yorum sayısı"))
    else:
        peers = ctx.peer_review_counts
        peer_note = ""
        below_peers = False
        if len(peers) >= 3:
            med = median(peers)
            peer_note = f" Aynı sektör/bölgedeki {len(peers)} rakibin ortanca yorum sayısı: {round(med)}."
            below_peers = med > 0 and count < med * 0.5
        if count == 0:
            severity, msg = "high", "Hiç Google yorumu yok"
        elif count < LOW_REVIEW_THRESHOLD:
            severity, msg = "medium", f"Google yorum sayısı düşük ({count})"
        elif below_peers:
            severity, msg = "medium", f"Yorum sayısı rakiplerin altında ({count})"
        else:
            severity, msg = None, None
        if severity:
            checks.append(Check(key="review_count", area="gbp", label="Yorum sayısı", status="problem", value=msg,
                                detail=f"Google profilinde {count} yorum var (eşik: {LOW_REVIEW_THRESHOLD}).{peer_note}", severity=severity, confidence="high",
                                why="Yorum sayısı hem güveni hem Google Haritalar sıralamasını doğrudan etkiler; müşteriler az yorumlu işletmeyi tercih etmez.",
                                services=(SVC_GBP,), category="gbp", source="places", short="düşük yorum sayısı"))
        else:
            checks.append(Check(key="review_count", area="gbp", label="Yorum sayısı", status="ok", value=f"{count} yorum.{peer_note}".strip(), category="gbp", source="places"))

    if rating is None:
        checks.append(_unknown("rating", "Ortalama puan"))
    elif rating < 4.0:
        checks.append(Check(key="rating", area="gbp", label="Ortalama puan", status="problem", value=f"Ortalama puan düşük ({rating})",
                            detail=f"Google ortalama puanı {rating}/5.", severity="medium", confidence="high",
                            why="4 altındaki puanlar müşterilerin işletmeyi seçmesini belirgin biçimde zorlaştırır; yorum yönetimi gerekir.",
                            services=(SVC_GBP,), category="gbp", source="places", short="düşük Google puanı"))
    else:
        checks.append(Check(key="rating", area="gbp", label="Ortalama puan", status="ok", value=f"{rating}/5", category="gbp", source="places"))

    last_review = business.last_review_at
    sampled = profile.get("reviews_sampled")
    if last_review is None:
        checks.append(_unknown("last_review", "Son yorum tarihi", detail="Google yorum tarihlerini bu sorguda döndürmedi." if sampled is None else ""))
    else:
        months = (ctx.now - last_review).days // 30
        note = f" (Google'ın döndürdüğü en fazla {sampled or 5} yorum arasında en yenisi)"
        if months >= 6:
            checks.append(Check(key="last_review", area="gbp", label="Son yorum tarihi", status="problem",
                                value=f"En yeni görülen yorum yaklaşık {months} ay önce", detail=f"{last_review.date().isoformat()} tarihli yorum{note}.",
                                severity="low", confidence="low", why="Uzun süredir yeni yorum almayan profil aktif görünmez ve güven kaybeder.",
                                services=(SVC_GBP,), category="gbp", source="places", short="yorum akışının durması"))
        else:
            checks.append(Check(key="last_review", area="gbp", label="Son yorum tarihi", status="ok", value=f"{last_review.date().isoformat()}{note}", category="gbp", source="places"))
    checks.append(_unknown("review_replies", "Yorumlara işletme yanıtı", detail=reason))
    return checks


def _gbp_field(key: str, label: str, value: str | None, missing_text: str, why: str, severity: str, services: tuple[str, ...] = (SVC_GBP,)) -> Check:
    if value:
        return Check(key=key, area="gbp", label=label, status="ok", value=value, category="gbp", source="places")
    return Check(key=key, area="gbp", label=label, status="problem", value=missing_text, detail=f"Google İşletme Profilinde {label.lower()} alanı boş.",
                 severity=severity, confidence="high", why=why, services=services, category="gbp", source="places",
                 short=f"{label.lower()} bilgisinin eksik olması")


def _gbp_checks_without_google(ctx: AnalysisContext, business) -> list[Check]:
    """Google profili okunamadı: hiçbir alan tahmin edilmez; NEDEN okunamadığı (erişim/eşleşme) açıkça yazılır."""
    status = ctx.source_status("google_maps")
    if status and status["status"] == "erisilemedi":
        note = f"Google İşletme Profili: ERİŞİLEMEDİ — {status['detail']}"
    elif status and status["status"] == "eslesme_yok":
        note = f"Google Haritalar kontrol edildi ancak bu işletmeyle güvenle eşleşen bir profil bulunamadı. {status['detail']}"
    else:
        note = "Google profil bilgisi için Google Haritalar sorgulanmadı (araştırma yapılmadı). Google Haritalar'da profili açarak elle kontrol edin."

    def osm(value: str | None) -> str:
        return f"{_GBP_UNAVAILABLE} (kayıtlarda: {value})" if value else f"{_GBP_UNAVAILABLE} (kayıtlarda bilgi yok)"

    checks: list[Check] = []
    if status and status["status"] == "eslesme_yok":
        checks.append(Check(
            key="profile_found", area="gbp", label="Google İşletme Profili var mı?", status="problem",
            value="Google Haritalar'da işletmeye ait bir profil bulunamadı",
            detail=note + " (Eşleştirme adı, konumu, telefonu ve adresi karşılaştırır; farklı adla kayıtlı bir profil olabilir.)",
            severity="high", confidence="low",
            why="Google Haritalar'da görünmeyen işletme, 'yakınımdaki ...' aramalarında hiç çıkmaz ve yorum/puan toplayamaz.",
            services=(SVC_GBP,), category="gbp", source="places", short="Google işletme profilinin bulunamaması", needs_verification=True,
        ))
    checks += [
        _unknown("primary_category", "Birincil kategori", f"{_GBP_UNAVAILABLE} (kayıtlardaki kategori: {business.category_label or 'bilinmiyor'})", note),
        _unknown("extra_categories", "Ek kategoriler", detail=note),
        _unknown("description", "İşletme açıklaması", detail=note),
        _unknown("services_list", "Hizmetler / ürünler bölümü", detail=note),
        _unknown("phone", "Telefon", osm(business.phone)),
        _unknown("website", "Web sitesi", osm(business.website)),
        _unknown("hours", "Çalışma saatleri", osm(business.opening_hours)),
        _unknown("photos", "Fotoğraflar", detail=note),
        _unknown("last_photo", "Son fotoğraf tarihi", detail=note),
        _unknown("review_count", "Yorum sayısı", detail=note),
        _unknown("rating", "Ortalama puan", detail=note),
        _unknown("last_review", "Son yorum tarihi", detail=note),
        _unknown("review_replies", "Yorumlara işletme yanıtı", detail=note),
    ]
    return checks


_MONTHS_TR = {"oca": 1, "şub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7, "ağu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12}


def _months_since(label: str | None, now: datetime) -> int | None:
    """'Eki 2023' -> şimdiye kadar geçen ay sayısı."""
    import re

    match = re.match(r"^(\w{3})\w*\s+(\d{4})", (label or "").strip())
    if not match or match.group(1).lower() not in _MONTHS_TR:
        return None
    return (now.year - int(match.group(2))) * 12 + now.month - _MONTHS_TR[match.group(1).lower()]


def _gbp_checks_from_profile(ctx: AnalysisContext, business, g: dict) -> list[Check]:
    """Google Haritalar'dan GERÇEKTEN okunan profil verisiyle kontroller. Okunamayan her alan 'Doğrulanamadı' kalır."""
    checks: list[Check] = []
    src = "places"
    limited = "Google oturumsuz 'sınırlı görünüm' bu bilgiyi vermiyor; profili Google Haritalar'da açarak elle kontrol edin."

    # ---- birincil kategori (Google'ın Türkçe kategori adı ↔ sektör ifadeleri)
    category = g.get("category")
    if not category:
        checks.append(Check(key="primary_category", area="gbp", label="Birincil kategori", status="problem", value="Birincil kategori belirlenmemiş",
                            detail="Google profilinde birincil kategori görünmüyor.", severity="medium", confidence="medium",
                            why="Kategori, Google Haritalar'da hangi aramalarda görüneceğinizi belirleyen en önemli alandır.",
                            services=(SVC_GBP,), category="gbp", source=src, short="birincil kategori eksikliği"))
    else:
        matches = _mentions_any(category, [*ctx.sector_phrases, *ctx.sector_name.replace("/", " ").split()])
        if matches:
            checks.append(Check(key="primary_category", area="gbp", label="Birincil kategori", status="ok", value=f"{category} (sektörle uyumlu)", category="gbp", source=src))
        else:
            checks.append(Check(key="primary_category", area="gbp", label="Birincil kategori", status="problem",
                                value=f'Kategori "{category}" sektörle uyumsuz görünebilir',
                                detail=f'Google birincil kategorisi "{category}"; "{ctx.sector_name}" sektörünün anahtar ifadeleriyle eşleşmiyor (farklı ama geçerli bir kategori olabilir).',
                                severity="low", confidence="low", why="Yanlış/uyumsuz kategori, doğru müşterilerin sizi Google Haritalar aramalarında görmesini engelleyebilir.",
                                services=(SVC_GBP,), category="gbp", source=src, short="kategori uyumsuzluğu", needs_verification=True))
    checks.append(_unknown("extra_categories", "Ek kategoriler", detail="Google Haritalar yalnızca ana kategoriyi gösteriyor; ek kategoriler oturumsuz görünümde okunamıyor."))

    # ---- açıklama ve hizmetler ("Hakkında" sekmesi okundu)
    if g.get("description"):
        checks.append(Check(key="description", area="gbp", label="İşletme açıklaması", status="ok", value=g["description"][:160], category="gbp", source=src))
    else:
        checks.append(Check(key="description", area="gbp", label="İşletme açıklaması", status="problem", value="Profilde işletme açıklaması yok",
                            detail="Google profilinin 'Hakkında' sekmesinde işletme açıklaması bulunamadı.", severity="medium", confidence="medium",
                            why="Açıklama, işletmenin ne yaptığını ve neden tercih edilmesi gerektiğini anlatan alandır; boşsa Google ve müşteri profili yeterince tanıyamaz.",
                            services=(SVC_GBP,), category="gbp", source=src, short="işletme açıklamasının olmaması"))
    attributes = g.get("attributes") or []
    if attributes:
        checks.append(Check(key="services_list", area="gbp", label="Hizmetler / özellikler", status="ok", value=", ".join(attributes[:6]), category="gbp", source=src))
    else:
        checks.append(Check(key="services_list", area="gbp", label="Hizmetler / özellikler", status="problem", value="Hizmet/özellik bilgisi eklenmemiş",
                            detail="Profilin 'Hakkında' sekmesinde hizmet seçeneği veya özellik listesi bulunamadı.", severity="low", confidence="low",
                            why="Hizmet ve özellikler profili zenginleştirir, müşterinin karar vermesini kolaylaştırır.",
                            services=(SVC_GBP,), category="gbp", source=src, short="hizmet/özellik bilgisinin eksikliği"))

    # ---- iletişim alanları
    checks.append(_gbp_field("phone", "Telefon", g.get("phone"), "Telefon numarası yok", "Profilde telefon yoksa arayan müşteri işletmeye tek dokunuşla ulaşamaz.", "medium"))
    checks.append(_gbp_field("website", "Web sitesi", g.get("website"), "Web sitesi yok", "Profildeki web sitesi bağlantısı Google'dan gelen ziyaretçinin ilk durağıdır.", "high",
                             services=(SVC_CORPORATE_SITE, SVC_GBP)))
    checks.append(_gbp_field("hours", "Çalışma saatleri", g.get("hours_text"), "Çalışma saatleri girilmemiş", "Saat bilgisi olmayan profil 'açık mı?' sorusunu cevaplayamaz ve daha az öne çıkar.", "medium"))

    # ---- fotoğraf: sayı sınırlı görünümde okunamaz; kapak fotoğrafı tarihi okunabilir
    checks.append(_unknown("photos", "Fotoğraf sayısı", detail=limited))
    cover = g.get("cover_photo_date")
    age = _months_since(cover, ctx.now)
    if cover and age is not None and age >= 24:
        checks.append(Check(key="last_photo", area="gbp", label="Kapak fotoğrafı tarihi", status="problem", value=f"Kapak fotoğrafı {cover} tarihli (yaklaşık {age // 12} yıl önce)",
                            detail=f"Profilde öne çıkan fotoğrafın çekilme tarihi {cover}. (Diğer fotoğrafların tarihleri okunamadı.)", severity="low", confidence="medium",
                            why="Eski fotoğraflar profili güncel/bakımsız gösterir; güncel ve kaliteli görsel tıklamayı ve güveni artırır.",
                            services=(SVC_MEDIA, SVC_GBP), category="gbp", source=src, short="eski profil fotoğrafı"))
    elif cover:
        checks.append(Check(key="last_photo", area="gbp", label="Kapak fotoğrafı tarihi", status="ok", value=cover, category="gbp", source=src))
    else:
        checks.append(_unknown("last_photo", "Kapak fotoğrafı tarihi", detail=limited))

    # ---- puan ve yorumlar
    count, rating = g.get("review_count"), g.get("rating")
    if count is None:
        checks.append(_unknown("review_count", "Yorum sayısı"))
    else:
        peers = ctx.peer_review_counts
        peer_note, below_peers = "", False
        if len(peers) >= 3:
            med = median(peers)
            peer_note = f" Aynı sektör/bölgedeki {len(peers)} rakibin ortanca yorum sayısı: {round(med)}."
            below_peers = med > 0 and count < med * 0.5
        severity = "high" if count == 0 else "medium" if count < LOW_REVIEW_THRESHOLD or below_peers else None
        if severity:
            msg = "Hiç Google yorumu yok" if count == 0 else (f"Google yorum sayısı düşük ({count})" if count < LOW_REVIEW_THRESHOLD else f"Yorum sayısı rakiplerin altında ({count})")
            checks.append(Check(key="review_count", area="gbp", label="Yorum sayısı", status="problem", value=msg,
                                detail=f"Google profilinde {count} yorum var (eşik: {LOW_REVIEW_THRESHOLD}).{peer_note}", severity=severity, confidence="high",
                                why="Yorum sayısı hem güveni hem Google Haritalar sıralamasını doğrudan etkiler; müşteriler az yorumlu işletmeyi tercih etmez.",
                                services=(SVC_GBP,), category="gbp", source=src, short="düşük yorum sayısı"))
        else:
            checks.append(Check(key="review_count", area="gbp", label="Yorum sayısı", status="ok", value=f"{count} yorum.{peer_note}".strip(), category="gbp", source=src))
    if rating is None:
        checks.append(_unknown("rating", "Ortalama puan"))
    elif rating < 4.0:
        checks.append(Check(key="rating", area="gbp", label="Ortalama puan", status="problem", value=f"Ortalama puan düşük ({str(rating).replace('.', ',')})",
                            detail=f"Google ortalama puanı {str(rating).replace('.', ',')}/5.", severity="medium", confidence="high",
                            why="4 altındaki puanlar müşterilerin işletmeyi seçmesini belirgin biçimde zorlaştırır; yorum yönetimi gerekir.",
                            services=(SVC_GBP,), category="gbp", source=src, short="düşük Google puanı"))
    else:
        checks.append(Check(key="rating", area="gbp", label="Ortalama puan", status="ok", value=f"{str(rating).replace('.', ',')}/5", category="gbp", source=src))

    last_relative = g.get("last_review_relative")
    last_at = g.get("last_review_at")
    if not last_relative:
        checks.append(_unknown("last_review", "Son yorum tarihi", detail="Google yorum tarihlerini okunamadı."))
    else:
        months = None
        if last_at:
            months = (ctx.now - datetime.fromisoformat(last_at)).days // 30
        note = f" (Google'ın '{g.get('reviews_sort') or 'en alakalı'}' sıralamasındaki ilk {g.get('reviews_sampled') or 0} yorumdan; göreli tarih olduğu için yaklaşıktır)"
        if months is not None and months >= 6:
            checks.append(Check(key="last_review", area="gbp", label="Son yorum tarihi", status="problem", value=f"En yeni yorum {last_relative}",
                                detail=f"En yeni yorum: {last_relative}{note}.", severity="low", confidence="medium",
                                why="Uzun süredir yeni yorum almayan profil aktif görünmez ve güven kaybeder.", services=(SVC_GBP,), category="gbp", source=src, short="yorum akışının durması"))
        else:
            checks.append(Check(key="last_review", area="gbp", label="Son yorum tarihi", status="ok", value=f"{last_relative} (yaklaşık)", detail=note.strip(" ()"), category="gbp", source=src))

    replies, sampled = g.get("owner_replies"), g.get("reviews_sampled") or 0
    if replies is None or not sampled:
        checks.append(_unknown("review_replies", "Yorumlara işletme yanıtı", detail="Yorumlar okunamadı."))
    elif sampled >= 3 and replies / sampled < 0.3:
        checks.append(Check(key="review_replies", area="gbp", label="Yorumlara işletme yanıtı", status="problem", value=f"İncelenen {sampled} yorumdan yalnızca {replies}'ine yanıt verilmiş",
                            detail=f"Google'ın en yeni {sampled} yorumundan {replies} tanesinde işletme yanıtı var.", severity="medium", confidence="medium",
                            why="Yorumlara yanıt vermek güven ve yerel sıralama sinyalidir; yanıtsız yorumlar ilgisiz görünür.", services=(SVC_GBP,), category="gbp", source=src, short="yorumlara yanıt verilmemesi"))
    else:
        checks.append(Check(key="review_replies", area="gbp", label="Yorumlara işletme yanıtı", status="ok", value=f"İncelenen {sampled} yorumdan {replies}'ine yanıt verilmiş", category="gbp", source=src))
    return checks


# ============================================================================ SOSYAL MEDYA
def build_social_checks(ctx: AnalysisContext) -> list[Check]:
    """Araştırmada bulunan (doğrulanmış) sosyal medya hesapları. Bulunamayan hesap 'yok' diye iddia edilmez: arama motorları
    bu ortamda güvenilir olmadığından yalnızca resmi web sitesi ve kayıtlar taranabilmiştir."""
    if not ctx.social:
        return []
    checks: list[Check] = []
    verified = [s for s in ctx.social if s["status"] == "dogrulandi"]
    for s in ctx.social:
        label = s["label"]
        if s["status"] == "dogrulandi":
            checks.append(Check(key=f"social_{s['network']}", area="social", label=label, status="ok", value=s["url"], detail=s.get("note", ""), category="social", source="website_crawl"))
        elif s["status"] == "tek_kaynak":
            checks.append(Check(key=f"social_{s['network']}", area="social", label=label, status="unknown", value=f"{s['url']} — Doğrulanamadı (tek kaynak)", detail=s.get("note", ""), category="social"))
        else:
            checks.append(Check(key=f"social_{s['network']}", area="social", label=label, status="unknown", value="Bulunamadı (resmi web sitesinde/kayıtlarda bağlantı yok)", detail=s.get("note", ""), category="social"))
    if not verified:
        checks.append(Check(
            key="social_presence", area="social", label="Sosyal medya varlığı", status="problem", value="Doğrulanmış sosyal medya hesabı bulunamadı",
            detail="Resmi web sitesinde ve kayıtlarda Instagram/Facebook/LinkedIn/YouTube bağlantısı bulunamadı. (Hesabın hiç olmadığı anlamına gelmez: arama motorları bu ortamda erişilemediği için yalnızca site ve kayıtlar tarandı.)",
            severity="medium", confidence="low", why="Sosyal medyada görünmeyen işletme, güven ve tekrar müşteri oluşturma fırsatını kaçırır; site ziyaretçisi hesaba yönlendirilemez.",
            services=(SVC_SOCIAL,), category="social", short="doğrulanmış sosyal medya hesabının bulunamaması", needs_verification=True,
        ))
    return checks
