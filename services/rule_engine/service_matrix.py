"""Hizmet matrisi: Mchttasarım'ın her hizmetini işletme için TEK TEK değerlendirir.

Amaç yalnızca teknik eksik listelemek değil, "Bu firmaya Mchttasarım olarak ne satabiliriz?" sorusunu GERÇEK VERİYE dayanarak yanıtlamaktır.

Sınıflandırma (her hizmet için):
  🟢 satis        — doğrulanmış (yüksek/orta güvenli) somut kanıt var: "Satış fırsatı"
  🟡 olasi        — zayıf/doğrulanmamış kanıt ya da sektörün doğasından çıkan güçlü ihtiyaç: "Olası fırsat" (görüşmede doğrulanmalı)
  ⚪ zayif        — kanıt yok, sektör uyumu da düşük: "Zayıf fırsat"
  🔴 uygun_degil  — hizmet bu işletme için anlamsız ya da zaten karşılanmış (ör. site sağlıklı → yeniden tasarım önerilmez)

İlkeler
- Kanıtsız hiçbir fırsat 🟢 olmaz; sektöre dayalı olasılıklar en fazla 🟡'dir ve "Tespit edilmedi — doğrulanmalı" diye açıkça yazılır.
- Web sitesi sağlıklıysa Web Tasarım önerilmez (🔴); sistem bunun yerine Yerel SEO, Google Ads, GBP, sosyal medya, baskı vb. hizmetleri değerlendirir.
- Ölçülemeyen (Doğrulanamadı) alanlardan sorun türetilmez.
"""

from dataclasses import dataclass, field
from typing import Callable

from services.knowledge.guides import SERVICE_TO_GUIDE, guide_for_check
from services.rule_engine.checks import (
    SVC_ADS,
    SVC_BRAND,
    SVC_CORPORATE_SITE,
    SVC_ECOM,
    SVC_GBP,
    SVC_GRAPHIC,
    SVC_LOCAL_SEO,
    SVC_MEDIA,
    SVC_PRINT,
    SVC_SEO,
    SVC_SIGN,
    SVC_SOCIAL,
    SVC_SOCIAL_ADS,
    SVC_WEB,
    SVC_BANNER,
    SVC_PROMO,
    AnalysisContext,
    Check,
)
from services.rule_engine.sales import CONFIDENCE_FACTOR, SEVERITY_WEIGHT, _EVENT_SECTORS, _FLEET_SECTORS, _VISUAL_GROUPS

SVC_LOGO = "Logo Tasarımı"
SVC_SOCIAL_CONTENT = "Sosyal Medya İçerik Üretimi"
SVC_CARD = "Kartvizit"
SVC_BROCHURE = "Broşür"
SVC_MENU = "Menü Baskı"
SVC_CATALOG = "Katalog"
SVC_INVITE = "Davetiye"
SVC_VEHICLE = "Araç Giydirme"

LEVEL_LABELS = {"satis": "🟢 Satış fırsatı", "olasi": "🟡 Olası fırsat", "zayif": "⚪ Zayıf fırsat", "uygun_degil": "🔴 Uygun değil"}
LEVEL_RANK = {"satis": 3, "olasi": 2, "zayif": 1, "uygun_degil": 0}
SECTOR_ONLY_POSSIBLE_LIMIT = 4  # kanıtsız (yalnızca sektöre dayalı) 🟡 sayısı; fazlası ⚪'e düşer — liste gürültüye boğulmasın


@dataclass
class Facts:
    ctx: AnalysisContext
    checks: dict[str, Check]
    business: object  # packages.db.models.Business (yalnızca okunur)
    signals: object | None
    has_website: bool
    site_measured: bool  # web sitesi açıldı ve ölçüldü
    site_js_only: bool
    gbp_available: bool
    reviews: int | None
    photos: int | None
    social_verified: list[dict]
    profile: object = field(init=False)
    group: str | None = field(init=False)
    sector: str = field(init=False)

    def __post_init__(self):
        self.profile = self.ctx.profile
        self.group = self.ctx.sector_group
        self.sector = self.ctx.sector_name

    def check(self, key: str) -> Check | None:
        return self.checks.get(key)

    def problem(self, key: str) -> Check | None:
        c = self.checks.get(key)
        return c if c is not None and c.status == "problem" else None


def _weight(check: Check) -> float:
    return SEVERITY_WEIGHT.get(check.severity, 0) * CONFIDENCE_FACTOR.get(check.confidence, 0.4)


def _evidence_from_check(check: Check) -> dict:
    guide = guide_for_check(check.area, check.key)
    return {
        "text": check.value, "detail": check.detail, "severity": check.severity, "confidence": check.confidence,
        "verified": (not check.needs_verification) and check.confidence in ("high", "medium"), "weight": round(_weight(check), 2),
        "check_key": check.key, "area": check.area, "guide_id": guide.id if guide else None, "why": check.why,
    }


def _derived(text: str, detail: str, *, weight: float, verified: bool, why: str = "") -> dict:
    return {"text": text, "detail": detail, "severity": "medium", "confidence": "medium" if verified else "low", "verified": verified, "weight": weight,
            "check_key": None, "area": "derived", "guide_id": None, "why": why}


@dataclass
class Spec:
    name: str
    commercial: int  # tahmini ticari anlamlılık 1-5 (sıralamada kullanılır)
    what: str  # Mchttasarım ne yapabilir
    pitch: str  # müşteriye nasıl anlatılır ({isletme}, {sektor}, {sehir})
    why_default: str  # neden satılabilir (kanıt yoksa genel gerekçe)
    check_keys: tuple[str, ...] = ()  # "web.mobile", "gbp.description", "social.social_presence"
    relevance: Callable[[Facts], float] = lambda f: 0.5
    derive: Callable[[Facts], list[dict]] | None = None
    not_applicable: Callable[[Facts], str | None] | None = None
    caveat: str | None = None
    recurring: bool = False  # aylık tekrarlayan gelir (SEO/Ads/sosyal medya) — ticari anlamlılığı artırır
    green_at: float = 2.0  # 🟢 için gereken doğrulanmış kanıt ağırlığı (küçük eksiklerin toplamı büyük bir hizmeti sattırmasın)


def _g(f: Facts) -> bool:
    return f.group in _VISUAL_GROUPS


# ------------------------------------------------------------------ hizmet tanımları
SPECS: list[Spec] = [
    Spec(SVC_CORPORATE_SITE, 5, "Kurumsal web sitesi + yerel SEO altyapısı kurar; iletişim, hizmet ve harita sayfalarını hazırlar.",
         "Google'da sizi arayan müşteri şu an size ait bir sayfaya ulaşamıyor. Hizmetlerinizi ve iletişim bilgilerinizi gösteren kurumsal bir site kurarsak sizi bulan müşteri doğrudan size ulaşır.",
         "Web sitesi, diğer tüm dijital çalışmaların temelidir.", ("web.presence",), lambda f: 0.9,
         not_applicable=lambda f: "Web sitesi mevcut." if f.has_website else None),
    Spec(SVC_WEB, 5, "Mevcut siteyi mobil uyumlu, hızlı ve iletişim/randevu odaklı olacak şekilde yeniler veya iyileştirir.",
         "Siteniz var ama ziyaretçiyi müşteriye çevirmekte zorlanan noktaları tespit ettik. Bunları düzelterek siteyi size daha çok arama ve randevu getiren bir araca dönüştürebiliriz.",
         "Mevcut sitedeki eksikler ziyaretçinin iletişime geçmeden ayrılmasına yol açabilir.",
         ("web.access", "web.https", "web.mobile", "web.speed", "web.conversion", "web.cta", "web.tel_link", "web.whatsapp", "web.maps_link", "web.booking",
          "web.services_page", "web.about", "web.references", "web.broken_links", "web.spam_content", "web.brand_match", "web.freshness", "web.peer_gap"),
         lambda f: 0.8, not_applicable=lambda f: None if f.has_website else "Web sitesi yok; bu durumda 'Kurumsal Web Sitesi' hizmeti geçerlidir.", green_at=3.5),
    Spec(SVC_ECOM, 5, "E-ticaret sitesi kurar: ürün katalogu, sepet, ödeme ve kargo entegrasyonu.",
         "Ürünlerinizi mağaza dışında da satabileceğiniz bir online mağaza kurarak size uzak şehirlerden de sipariş getirebiliriz.",
         "Ürün satan işletmenin online satış kanalı yoksa mağaza dışındaki talep kaçabilir.", ("web.ecommerce",),
         lambda f: 0.75 if f.profile.sells_products else 0.0,
         not_applicable=lambda f: None if f.profile.sells_products else "Bu sektörde online ürün satışı yaygın değil."),
    Spec(SVC_SEO, 4, "Başlık, açıklama, H1, içerik, teknik SEO ve ölçüm altyapısını düzenler; düzenli içerik planı çıkarır.",
         "Siteniz Google'da 'hizmet + şehir' aramalarında daha görünür olabilir. Sayfa içi ve teknik eksikleri düzeltip ölçüm kurarsak ücretsiz (organik) müşteri artabilir.",
         "Sayfa içi ve teknik eksikler sitenin Google'da görünmesini zorlaştırıyor olabilir.",
         ("web.title", "web.title_keywords", "web.meta_description", "web.h1", "web.heading_structure", "web.content_volume", "web.schema", "web.indexing", "web.sitemap",
          "web.images", "web.analytics", "web.internal_links", "web.blog", "web.peer_gap"), lambda f: 0.8, recurring=True, green_at=3.0,
         not_applicable=lambda f: None if f.has_website else "Web sitesi yok; önce site kurulmalı (Kurumsal Web Sitesi)."),
    Spec(SVC_LOCAL_SEO, 4, "Şehir/ilçe odaklı sayfa ve başlıklar, LocalBusiness verisi, harita ve yerel içerikle 'yakınımdaki' aramalarda görünürlüğü artırır.",
         "İnsanlar '{sektor} {sehir}' diye aradığında sizden önce rakipleriniz çıkıyorsa müşteri onlara gidiyor. Yerel SEO ile bu aramalarda öne çıkmayı hedefleriz.",
         "Yerel aramalarda görünürlük, yakındaki hazır müşterinin işletmeye ulaşmasını belirler.",
         ("web.local_seo", "web.title_keywords", "web.presence"), lambda f: 0.85 if f.profile.local_intent else 0.2, recurring=True,
         not_applicable=lambda f: None if f.profile.local_intent else "Bu sektörde yerel arama talebi baskın değil."),
    Spec(SVC_GBP, 3, "Google İşletme Profilini tamamlar: kategori, açıklama, hizmetler, fotoğraf, çalışma saatleri, yorum yanıt planı.",
         "Google Haritalar'da profiliniz eksik alanlar yüzünden rakiplerin gerisinde kalıyor olabilir. Profili tamamlayıp yorum/fotoğraf düzenini kurarız.",
         "Google Haritalar'da güven ve görünürlüğü doğrudan profilin doluluğu ve yorumlar etkiler.",
         ("gbp.profile_found", "gbp.primary_category", "gbp.extra_categories", "gbp.description", "gbp.services_list", "gbp.photos", "gbp.last_photo",
          "gbp.review_count", "gbp.rating", "gbp.last_review", "gbp.review_replies", "gbp.hours"), lambda f: 0.8 if f.profile.local_intent else 0.4, recurring=True),
    Spec(SVC_ADS, 4, "Google Ads arama kampanyası kurar; dönüşüm (arama/WhatsApp/form) takibini bağlar ve aylık optimize eder.",
         "Acil ihtiyacı olan müşteri Google'da arama yaptığında reklamla en üstte çıkabilirsiniz. Önce ölçümü kurar, sonra bütçenizi en çok müşteri getiren aramalara harcarız.",
         "Yüksek yerel talebi olan sektörde reklam, hızlı müşteri akışı sağlar; ölçüm kurulmadan reklam verimsiz olur.",
         (), lambda f: 0.9 if (f.profile.local_intent and (f.profile.storefront or f.profile.appointment_based)) else (0.6 if f.profile.local_intent else 0.25), recurring=True,
         caveat="İşletmenin Google Ads kullanıp kullanmadığı doğrulanamaz; görüşmede sorulmalı."),
    Spec(SVC_SOCIAL, 4, "Sosyal medya hesaplarını kurar/düzenler; aylık içerik takvimi, paylaşım ve topluluk yönetimi yapar.",
         "Müşterileriniz sizi sosyal medyada da arıyor. Düzenli ve profesyonel paylaşımlarla güven ve tekrar müşteri kazanabilirsiniz.",
         "Doğrulanabilir bir sosyal medya varlığı marka güveni ve tekrar müşteri fırsatı sağlar.",
         ("social.social_presence", "web.social_links"), lambda f: 0.7 if _g(f) else 0.55, recurring=True,
         caveat="Sosyal medyada hesabın hiç olmadığı iddia edilmez; yalnızca site ve kayıtlarda bulunamadı."),
    Spec(SVC_SOCIAL_CONTENT, 3, "Ürün/hizmet/mekân için aylık görsel ve kısa video içeriği (reels/story) üretir.",
         "Rakiplerden ayrışmanızı sağlayacak düzenli görsel içerik üretiriz; sosyal medyanız ve profiliniz canlı görünür.",
         "Görsel etkisi yüksek sektörlerde düzenli içerik güveni ve tıklanmayı artırır.", ("social.social_presence",), lambda f: 0.7 if _g(f) else 0.3, recurring=True),
    Spec(SVC_SOCIAL_ADS, 3, "Instagram/Facebook reklam kampanyası kurar, hedef kitleyi belirler ve sonuçları raporlar.",
         "Sosyal medya hesabınız var; reklamla bölgenizdeki potansiyel müşterilere hedefli ulaşabilirsiniz.",
         "Aktif hesabı olan işletme, reklamla kısa sürede yerel kitleye ulaşabilir.", (),
         lambda f: 0.6 if (f.social_verified and _g(f)) else (0.45 if f.social_verified else 0.1), recurring=True,
         not_applicable=lambda f: None if f.social_verified else "Doğrulanmış sosyal medya hesabı yok; önce hesap/içerik gerekir.",
         caveat="Reklam kullanıp kullanmadığı doğrulanamadı."),
    Spec(SVC_MEDIA, 3, "Mekân, ürün, ekip ve hizmet için profesyonel fotoğraf/video çekimi yapar; profil ve site için hazırlar.",
         "Profesyonel görseller güveni ve tıklanmayı artırır. Profil ve siteniz için güncel çekim yaparız.",
         "Güncel ve kaliteli görsel eksikliği profil ve sitede tıklamayı ve güveni azaltabilir.", ("gbp.photos", "gbp.last_photo"), lambda f: 0.75 if _g(f) else 0.4),
    Spec(SVC_GRAPHIC, 2, "Sosyal medya, sunum, afiş ve dijital görselleri marka diline uygun tasarlar.",
         "Tüm görselleriniz aynı marka diliyle tutarlı olursa profesyonel ve akılda kalıcı görünürsünüz.",
         "Tutarsız veya eksik görseller profesyonellik algısını etkileyebilir.", ("web.images", "web.brand_match"), lambda f: 0.5),
    Spec(SVC_BRAND, 3, "Logo, renk, yazı tipi ve basılı/dijital uygulamalarıyla tutarlı bir kurumsal kimlik oluşturur.",
         "İşletmenizin tabeladan kartvizite, sosyal medyadan siteye aynı güveni veren bir kimliği olsun.",
         "Logo ve kimlik tutarlılığı işletmenin ilk izlenimini belirler.", ("web.brand_match",), lambda f: 0.5,
         derive=lambda f: [_derived("İşletme adı kaynaklarda tutarsız görünüyor", "Farklı kaynaklar işletme adını farklı yazıyor.", weight=1.5, verified=True)]
         if any(v.get("key") == "name" and v.get("status") == "celiskili" for v in (f.ctx.research or {}).get("verdicts", {}).values()) else [],
         caveat="Mevcut logo/kimlik materyalleri doğrulanamadı; görüşmede görülmeli."),
    Spec(SVC_LOGO, 2, "İşletme için yeni/yenilenmiş logo tasarlar ve kullanım kılavuzu hazırlar.",
         "Logonuzu güncel ve her mecrada okunaklı hale getirebiliriz.",
         "Logonun güncelliği ve okunaklılığı görsel izlenimi etkiler.", ("web.brand_match",), lambda f: 0.3, caveat="Mevcut logo doğrulanamadı."),
    Spec(SVC_PRINT, 2, "Kartvizit, broşür, katalog, menü ve kurumsal baskı işlerini tasarlar ve basar.",
         "{print_need} gibi basılı materyallerinizi tasarlayıp basabiliriz; tek noktadan teslim.",
         "Basılı materyaller yüz yüze ilk izlenimin parçasıdır.", (), lambda f: 0.65 if f.profile.storefront else 0.4, caveat="Mevcut basılı materyaller doğrulanamadı."),
    Spec(SVC_CARD, 1, "Kurumsal kimliğe uygun kartvizit tasarlar ve basar.",
         "Kartvizitiniz işletmenizin ilk yüz yüze temsilcisidir; logonuza uygun güncel bir tasarım hazırlayabiliriz.",
         "Yüz yüze ve randevulu işlerde kartvizit temel iletişim aracıdır.", (), lambda f: 0.7 if (f.profile.storefront or f.profile.appointment_based) else 0.45),
    Spec(SVC_BROCHURE, 2, "Hizmet/ürün tanıtım broşürü tasarlar ve basar.",
         "Hizmetlerinizi anlatan şık bir broşürle müşteriye elden bilgi bırakabilirsiniz.",
         "Anlatılması gereken hizmeti olan sektörlerde broşür karar sürecini destekler.", (),
         lambda f: 0.7 if (f.profile.appointment_based or f.group in ("Eğitim", "Emlak, İnşaat ve Yapı", "Konaklama ve Turizm", "Sağlık ve Tıp")) else 0.4),
    Spec(SVC_MENU, 2, "Restoran/kafe için menü tasarımı ve baskısı (basılı ve QR) yapar.",
         "Menünüzü markanıza uygun, okunaklı ve cazip bir tasarımla yenileyebiliriz.",
         "Yeme-içmede menü, satışı doğrudan etkileyen bir görsel araçtır.", (), lambda f: 0.9 if f.group == "Yeme-İçme" else 0.0,
         not_applicable=lambda f: None if f.group == "Yeme-İçme" else "Bu sektörde menü baskısı yaygın değil.", caveat="Mevcut menünün durumu doğrulanamadı."),
    Spec(SVC_CATALOG, 3, "Ürün/proje kataloğu tasarlar ve basar (basılı + PDF).",
         "Ürün ve projelerinizi anlatan profesyonel bir katalogla satış görüşmelerinizi güçlendirebilirsiniz.",
         "Ürün/proje odaklı sektörlerde katalog satış aracıdır.", (),
         lambda f: 0.75 if (f.profile.sells_products or f.group in ("Emlak, İnşaat ve Yapı", "Sanayi, Toptan ve Tarım", "Ev, Mobilya ve Dekorasyon")) else 0.0,
         not_applicable=lambda f: None if (f.profile.sells_products or f.group in ("Emlak, İnşaat ve Yapı", "Sanayi, Toptan ve Tarım", "Ev, Mobilya ve Dekorasyon")) else "Bu sektörde katalog ihtiyacı belirgin değil."),
    Spec(SVC_INVITE, 1, "Davetiye ve etkinlik basılı materyali (davetiye, program, isimlik) tasarlar ve basar.",
         "Etkinlik ve davetleriniz için tasarım ve baskıyı tek noktadan yapabiliriz.",
         "Düğün/etkinlik/organizasyon işletmesinin müşterisi davetiye ihtiyacı duyar.", (), lambda f: 0.7 if f.sector in _EVENT_SECTORS else 0.0,
         not_applicable=lambda f: None if f.sector in _EVENT_SECTORS else "Bu sektörde davetiye ihtiyacı yaygın değil."),
    Spec(SVC_BANNER, 2, "Kampanya/duyuru için branda, afiş ve vinil baskı üretir.",
         "Kampanya ve duyurularınız için dikkat çekici branda/afiş hazırlayabiliriz.",
         "Fiziksel mekânı olan işletmede dış mekân görünürlüğü yoldan geçen müşteriyi çeker.", (), lambda f: 0.5 if f.profile.storefront else 0.0,
         not_applicable=lambda f: None if f.profile.storefront else "Fiziksel mekânı olmayan sektör."),
    Spec(SVC_SIGN, 3, "Tabela tasarımı, üretimi ve montajı (ışıklı/ışıksız, cephe giydirme).",
         "Dükkânınızın dışarıdan görünürlüğünü artıran, markanıza uygun bir tabela hazırlayabiliriz.",
         "Yoldan geçen müşteri için tabela ilk temas noktasıdır.", (), lambda f: 0.75 if f.profile.storefront else 0.0,
         not_applicable=lambda f: None if f.profile.storefront else "Fiziksel mekânı olmayan sektör.", caveat="Mevcut tabelanın durumu yerinde doğrulanmalı."),
    Spec(SVC_VEHICLE, 3, "Servis/araç filosu için araç giydirme tasarımı ve uygulaması.",
         "Araçlarınız gezen bir reklam panosuna dönüşebilir; logonuzu ve iletişim bilgilerinizi yolda binlerce kişiye gösterir.",
         "Araç filosu/servis aracı olan işletmeler için giydirme sürekli görünürlük sağlar.", (), lambda f: 0.7 if f.sector in _FLEET_SECTORS else 0.0,
         not_applicable=lambda f: None if f.sector in _FLEET_SECTORS else "Bu sektörde araç filosu yaygın değil.", caveat="İşletmenin aracı olup olmadığı doğrulanamadı."),
    Spec(SVC_PROMO, 2, "Logolu promosyon ürünleri (kalem, ajanda, çanta, magnet vb.) tedarik eder.",
         "Müşterilerinize logolu hediyelerle markanızı hatırlatabilirsiniz.",
         "Tekrar eden müşterisi olan işletmede promosyon ürünleri marka hatırlanırlığını artırır.", (),
         lambda f: 0.6 if (f.group in ("Sağlık ve Tıp", "Otomotiv", "Emlak, İnşaat ve Yapı", "Profesyonel Hizmetler", "Eğitim", "Yeme-İçme", "Perakende ve Mağazacılık") or (f.reviews or 0) >= 50) else 0.4),
]


# ------------------------------------------------------------------ özel kanıt türetmeleri (Ads, GBP yokluğu vb.)
def _ads_evidence(f: Facts) -> list[dict]:
    out: list[dict] = []
    analytics = f.check("web.analytics")
    if analytics is not None and analytics.status == "problem" and f.has_website:
        out.append(_derived("Sitede reklam/dönüşüm ölçümü (Google Ads etiketi, Analytics, Etiket Yöneticisi) tespit edilmedi", analytics.detail, weight=2.0, verified=True,
                            why="Ölçüm altyapısı olmadan Google Ads bütçesi verimli kullanılamaz; kurulum + kampanya birlikte satılabilir."))
    if f.profile.local_intent and not f.has_website and f.business.phone:
        out.append(_derived("Web sitesi olmadan reklam trafiği yalnızca telefonla karşılanabilir", "Doğrulanmış web sitesi yok; telefon dışında dönüşüm noktası yok.", weight=0.8, verified=False))
    return out


def _social_derived(f: Facts) -> list[dict]:
    out: list[dict] = []
    if f.social_verified and f.has_website and f.check("web.social_links") is not None and f.check("web.social_links").status == "problem":
        out.append(_derived("Sosyal medya hesabı var ancak web sitesinde bağlantısı yok", "Doğrulanmış hesap bulundu, fakat ana sayfada sosyal medya bağlantısı görülmedi.", weight=0.8, verified=True))
    return out


_DERIVE = {SVC_ADS: _ads_evidence, SVC_SOCIAL: _social_derived}

# Ads etiketi bulunduysa reklam zaten veriliyor olabilir → hizmet önerisi değil
def _ads_not_applicable(f: Facts) -> str | None:
    tools = list(getattr(f.signals, "analytics_tools", None) or []) if f.signals is not None else []
    if "google_ads" in tools:
        return "Sitede Google Ads etiketi görüldü: reklam veriyor olabilir (mevcut kampanya optimizasyonu ayrıca konuşulabilir)."
    return None


def _web_healthy(f: Facts) -> bool:
    """Web sitesi ölçüldü ve mobil/HTTPS/iletişim gibi temel alanlarda sorun yok."""
    if not (f.has_website and f.site_measured):
        return False
    keys = ("web.access", "web.https", "web.mobile", "web.speed", "web.conversion", "web.cta", "web.tel_link", "web.whatsapp", "web.maps_link", "web.services_page",
            "web.broken_links", "web.spam_content", "web.brand_match", "web.freshness")
    return not any(f.problem(k) is not None for k in keys)


def _grade(spec: Spec, f: Facts) -> dict:
    evidence: list[dict] = []
    for k in spec.check_keys:
        check = f.checks.get(k)
        if check is not None and check.status == "problem":
            evidence.append(_evidence_from_check(check))
    if spec.derive:
        evidence += spec.derive(f)
    if spec.name in _DERIVE:
        evidence += _DERIVE[spec.name](f)
    evidence.sort(key=lambda e: -e["weight"])

    verified_weight = sum(e["weight"] for e in evidence if e["verified"])
    any_strong = any(e["verified"] and e["severity"] == "high" for e in evidence)
    total_weight = sum(e["weight"] for e in evidence)
    relevance = max(0.0, min(1.0, spec.relevance(f)))

    reason_na = spec.not_applicable(f) if spec.not_applicable else None
    if spec.name == SVC_ADS and reason_na is None:
        reason_na = _ads_not_applicable(f)
    if spec.name == SVC_WEB and reason_na is None and _web_healthy(f) and not evidence:
        reason_na = "Web sitesi teknik olarak sağlıklı görünüyor (mobil, HTTPS, hız, iletişim noktaları ölçüldü); yeniden tasarım önerilmez."

    sector_only = False
    if reason_na is not None and not (evidence and verified_weight >= 2.0 and spec.name != SVC_WEB):
        level = "uygun_degil"
    elif verified_weight >= spec.green_at or any_strong:
        level = "satis"
    elif evidence:
        level = "olasi" if (total_weight >= 1.0 or relevance >= 0.5) else "zayif"
    else:
        sector_only = True
        level = "olasi" if relevance >= 0.65 else ("zayif" if relevance >= 0.3 else "uygun_degil")
        if spec.name == SVC_WEB and f.has_website and not f.site_measured:
            level, sector_only = "zayif", True
    if level == "satis" and spec.name in (SVC_SOCIAL, SVC_SOCIAL_CONTENT) and not any(e["verified"] for e in evidence):
        level = "olasi"

    problem = evidence[0]["text"] if evidence else ("Tespit edilmedi — sektöre dayalı olası ihtiyaç." if level in ("olasi", "zayif") else (reason_na or "Uygun değil."))
    why = next((e["why"] for e in evidence if e["why"]), "") or spec.why_default
    caveat = spec.caveat if (level in ("olasi", "zayif") or any(not e["verified"] for e in evidence)) else None
    guide = SERVICE_TO_GUIDE.get(spec.name)
    ev_guide = next((e["guide_id"] for e in evidence if e["guide_id"]), None)
    return {
        "service": spec.name, "level": level, "level_label": LEVEL_LABELS[level], "verified": level == "satis",
        "problem": problem, "evidence": evidence[:6], "why": why, "what": spec.what, "pitch": spec.pitch, "caveat": caveat,
        "not_applicable_reason": reason_na if level == "uygun_degil" else None, "commercial": spec.commercial, "recurring": spec.recurring,
        "relevance": round(relevance, 2), "evidence_weight": round(total_weight, 2), "sector_only": sector_only and level in ("olasi", "zayif"),
        "guide_id": ev_guide or guide,
    }


def _rank_value(item: dict) -> float:
    """Sıralama: en güçlü tekil kanıt + (sınırlı) kanıt toplamı + ticari anlamlılık. Çok sayıda küçük bulgu tek güçlü kanıtı geçemez."""
    strongest = item["evidence"][0]["weight"] if item["evidence"] else 0.0
    return strongest * 1.0 + min(item["evidence_weight"], 6.0) * 0.25 + item["commercial"] * (1.0 if item["recurring"] else 0.9)


def _rank_key(item: dict):
    order = next((n for n, spec in enumerate(SPECS) if spec.name == item["service"]), 99)
    return (-LEVEL_RANK[item["level"]], -_rank_value(item), order)


def build_service_matrix(ctx: AnalysisContext, checks: list[Check], *, business, signals=None, has_website: bool = False) -> dict:
    """Her hizmeti değerlendirir. Döndürür: {"items": [...sıralı...], "counts": {...}, "top": [...]}"""
    by_key: dict[str, Check] = {}
    for c in checks:
        key = f"{'web' if c.area == 'website' else c.area}.{c.key}"
        by_key[key] = c
    site_ok = bool(signals is not None and getattr(signals, "success", False))
    facts = Facts(
        ctx=ctx, checks=by_key, business=business, signals=signals, has_website=has_website, site_measured=site_ok and not getattr(signals, "js_rendered_hint", False),
        site_js_only=bool(signals is not None and getattr(signals, "js_rendered_hint", False)), gbp_available=ctx.google_profile is not None or ctx.is_google_data,
        reviews=getattr(business, "google_review_count", None), photos=getattr(business, "photo_count", None),
        social_verified=[s for s in ctx.social if s.get("status") == "dogrulandi"],
    )
    items = [_grade(spec, facts) for spec in SPECS]
    # kanıtsız (yalnızca sektöre dayalı) 🟡'ler en fazla SECTOR_ONLY_POSSIBLE_LIMIT; fazlası ⚪'e düşer
    sector_only = sorted((i for i in items if i["level"] == "olasi" and i["sector_only"]), key=lambda i: -(i["relevance"] * i["commercial"]))
    for item in sector_only[SECTOR_ONLY_POSSIBLE_LIMIT:]:
        item["level"], item["level_label"] = "zayif", LEVEL_LABELS["zayif"]
    items.sort(key=_rank_key)
    # "primary": en üstteki 🟢 (yoksa 🟡); ikinci hizmet: sonraki
    actionable = [i for i in items if i["level"] in ("satis", "olasi")]
    for n, item in enumerate(actionable[:2]):
        item["primary"] = n == 0
    counts = {level: sum(1 for i in items if i["level"] == level) for level in LEVEL_LABELS}
    return {"items": items, "counts": counts, "top": [i["service"] for i in actionable[:3]]}
