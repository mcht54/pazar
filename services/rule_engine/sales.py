"""Satış fırsatı değerlendirmesi — kontrol sonuçlarından (Check) seviye, gerekçe ve hizmet önerisi üretir.

Tamamen deterministik ve AÇIKLANABİLİR: ekrana anlamsız bir puan basılmaz; seviye (Yüksek/Orta/Düşük/
Belirsiz) her zaman "neden" cümlesiyle gelir. İç sayı (rank_score) sadece listeyi sıralamak içindir.

Seviye mantığı:
- Her sorun kontrolü: puan = önem (yüksek 3 / orta 2 / düşük 1) × güven (yüksek 1.0 / orta 0.75 / düşük 0.4).
- Düşük önemli bulguların (blog, hakkımızda, sitemap...) toplam katkısı LOW_POINTS_CAP ile sınırlıdır:
  onlarca küçük eksik tek başına "Yüksek" yapmaz.
- "Doğrulanmış güçlü bulgu" = güveni YÜKSEK ve önemi orta/yüksek olan sorun.
- Önerilen ilk hizmet: en güçlü tekil kanıta sahip hizmet (eşitlikte temel hizmetler önce), toplam puana göre değil.
- Yüksek : (güçlü doğrulanmış YÜKSEK önemli bulgu ve puan >= 4) VEYA (en az 2 güçlü doğrulanmış bulgu ve puan >= 7)
           VEYA puan >= 9 (birçok alanda somut eksik).
- Orta   : toplam puan >= 2.
- Düşük  : somut bir eksik yok / çok az.
- Belirsiz: hiçbir sorun bulunamadı ama veri de yok (site analiz edilemedi vb.) — "iyi" denmez.
Güveni düşük/orta olan kayıt-kaynaklı çıkarımlar (ör. OSM'de web sitesi görünmemesi) tek başına
"Yüksek" üretemez ve "doğrulama gerekli" olarak işaretlenir. Güçlü siteler (sorunsuz) yukarı çıkmaz.
"""

from dataclasses import dataclass, field
from urllib.parse import quote

from packages.localization import tr_capitalize_first

from services.rule_engine.checks import (
    SVC_ADS,
    SVC_BANNER,
    SVC_CORPORATE_SITE,
    SVC_ECOM,
    SVC_BRAND,
    SVC_GBP,
    SVC_GRAPHIC,
    SVC_LOCAL_SEO,
    SVC_MEDIA,
    SVC_PRINT,
    SVC_PROMO,
    SVC_SEO,
    SVC_SIGN,
    SVC_SOCIAL,
    SVC_SOCIAL_ADS,
    SVC_WEB,
    AnalysisContext,
    Check,
)

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1, "none": 0}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.75, "low": 0.4}
SEVERITY_LABEL_TR = {"high": "Yüksek", "medium": "Orta", "low": "Düşük", "none": "-"}
PER_SERVICE_CAP = 9.0  # tek bir hizmet alanında çok sayıda küçük bulgu hizmet sıralamasını şişirmesin
LOW_POINTS_CAP = 2.0  # düşük önemli bulguların seviyeye toplam katkısı
MEDIUM_LEVEL_MIN_POINTS = 2.0
HIGH_LEVEL_POINTS_ANY = 9.0
HIGH_LEVEL_POINTS_ONE_STRONG_HIGH = 4.0
HIGH_LEVEL_POINTS_TWO_STRONG = 7.0

LEVEL_ORDER = {"Yüksek": 3, "Orta": 2, "Düşük": 1, "Belirsiz": 0}
SERVICE_ORDER = [SVC_CORPORATE_SITE, SVC_WEB, SVC_ECOM, SVC_LOCAL_SEO, SVC_SEO, SVC_GBP, SVC_ADS, SVC_SOCIAL, SVC_SOCIAL_ADS, SVC_MEDIA, SVC_BRAND, SVC_GRAPHIC, SVC_PRINT, SVC_BANNER, SVC_SIGN, SVC_PROMO]


@dataclass
class ServiceOpportunity:
    service: str
    points: float
    problems: list[Check] = field(default_factory=list)


@dataclass
class Assessment:
    level: str
    level_reason: str
    rank_score: float
    needs_verification: bool
    services: list[ServiceOpportunity]
    possible_services: list[dict]
    top_opportunity: str | None
    why_call: str
    talking_point: str
    sales_note: str
    verification_steps: list[str]
    gaps: list[Check]  # ağırlığa göre sıralı sorunlar
    strengths: list[Check]


def _weight(check: Check) -> float:
    return SEVERITY_WEIGHT.get(check.severity, 0) * CONFIDENCE_FACTOR.get(check.confidence, 0.4)


def _join_tr(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ve " + items[-1]


def _cap_first(text: str) -> str:
    return tr_capitalize_first(text)


def _service_rank(service: str) -> int:
    return SERVICE_ORDER.index(service) if service in SERVICE_ORDER else len(SERVICE_ORDER)


def _issue_text(opportunity: ServiceOpportunity, limit: int = 3) -> str:
    shorts: list[str] = []
    for check in sorted(opportunity.problems, key=_weight, reverse=True):
        if check.short and check.short not in shorts:
            shorts.append(check.short)
    return _join_tr(shorts[:limit])


# ---------------------------------------------------------------------------- şablonlar
_WHY_TEMPLATES = {
    SVC_CORPORATE_SITE: "{top_value}; Google'da '{phrase} {place}' araması yapan potansiyel müşteriler işletmeye dijital olarak ulaşamıyor olabilir.",
    SVC_WEB: "Web sitesi mevcut ancak {issues} tespit edildi; ziyaretçilerin iletişime geçmeden siteyi terk etme riski var.",
    SVC_SEO: "Web sitesinde {issues} tespit edildi; Google'da '{phrase} {place}' gibi aramalarda görünürlük kaybı yaşanıyor olabilir.",
    SVC_GBP: "Google İşletme Profilinde {issues} tespit edildi; Google Haritalar aramalarında rakiplerin gerisinde kalınıyor olabilir.",
    SVC_ECOM: "Ürün satan bir işletme olmasına rağmen {issues}; mağaza dışındaki online talep kaçıyor olabilir.",
    SVC_SOCIAL: "{issues}; sosyal medya üzerinden müşteriye ulaşma fırsatı yeterince kullanılmıyor olabilir.",
    SVC_GRAPHIC: "{issues}; görsel kimlik ve içerik kalitesi iyileştirilebilir.",
    SVC_LOCAL_SEO: "{issues} tespit edildi; '{phrase} {place}' gibi yerel aramalarda ve Google Haritalar'da bölge odaklı görünürlük kaybı yaşanıyor olabilir.",
    SVC_MEDIA: "{issues}; güncel ve profesyonel görsel eksikliği Google profilinde ve sitede tıklamayı ve güveni azaltıyor olabilir.",
}

_PITCH_TEMPLATES = {
    SVC_CORPORATE_SITE: "Google'da '{phrase} {place}' araması yapan potansiyel müşterilere bir web sitesiyle görünmek mümkün; şu an bu kanaldan gelen talep kaçıyor olabilir.",
    SVC_WEB: "Web siteniz mevcut ancak {issues} gibi geliştirilebilecek alanlar bulunduğu için Google'dan gelen potansiyel müşterilerde kayıp yaşanabilir.",
    SVC_SEO: "Web siteniz mevcut ancak {issues} nedeniyle '{phrase} {place}' aramalarında görünürlüğünüz zayıf kalabilir; yapılacak SEO düzeltmeleriyle Google'dan gelen müşteri sayısı artırılabilir.",
    SVC_GBP: "Google İşletme Profilinizde {issues} bulunuyor; profil eksiksiz ve güncel olduğunda Google Haritalar'da arama yapan müşteriler size daha kolay ulaşır.",
    SVC_ECOM: "Ürün satışınızı internete taşıyacak bir altyapı görünmüyor ({issues}); online satışla mağaza dışındaki talebi de karşılayabilirsiniz.",
    SVC_SOCIAL: "Sosyal medya varlığınız güçlendirilebilir ({issues}); düzenli içerikle hem güven hem tekrar müşteri artar.",
    SVC_GRAPHIC: "Görsel kimliğinizde iyileştirilebilecek noktalar var ({issues}); profesyonel tasarım güveni artırır.",
    SVC_LOCAL_SEO: "Web siteniz {place} odaklı yerel aramalara yeterince hazır değil ({issues}); '{phrase} {place}' aradığında sizi bulan müşteri sayısı yerel SEO ile artırılabilir.",
    SVC_MEDIA: "Profilinizdeki/sitenizdeki görseller güncellenebilir ({issues}); profesyonel fotoğraf ve video, Google'da ve sosyal medyada güveni ve tıklamayı artırır.",
}

_TALKING_POINTS = {
    SVC_CORPORATE_SITE: "Görüşmeye 'Müşterileriniz sizi Google'da bulduktan sonra nereden bilgi alıyor?' sorusuyla başlayın; ardından birlikte Google'da '{phrase} {place}' araması yapıp işletmenin web sitesiyle görünüp görünmediğine bakın.",
    SVC_WEB: "Görüşmeye işletmenin kendi sitesini birlikte telefonda açarak başlayın; en somut bulgudan ('{top_value}') yola çıkıp ziyaretçinin bu noktada nasıl kaybedildiğini gösterin.",
    SVC_SEO: "Google'da '{phrase} {place}' araması yapıp işletmenin sonuçlarda nerede çıktığını gösterin; ardından en somut eksiği ('{top_value}') örnekleyip düzeltilmiş bir başlık/açıklama önerisi sunun.",
    SVC_GBP: "Google Haritalar'da işletmenin profilini birlikte açın; '{top_value}' gibi eksikleri ve aynı sektördeki rakip profillerle farkı gösterin.",
    SVC_ECOM: "Mağazadaki bir ürünün online satışının nasıl olabileceğini örnekleyerek başlayın; rakiplerin online satış yapıp yapmadığını birlikte inceleyin.",
    SVC_SOCIAL: "İşletmenin mevcut sosyal medya hesaplarını birlikte açıp paylaşım düzenini konuşarak başlayın; sitede/kayıtlarda hesap bağlantısının görünmediğini belirtin.",
    SVC_GRAPHIC: "Mevcut görsellerin (site/profil fotoğrafları) birlikte incelenmesiyle başlayın; profesyonel görselin dönüşüme etkisini örnekleyin.",
    SVC_LOCAL_SEO: "Google'da '{phrase} {place}' araması yapıp işletmenin sitesinin ve profilinin bu aramada nasıl göründüğünü birlikte inceleyin; en somut eksiği ('{top_value}') gösterin.",
    SVC_MEDIA: "İşletmenin Google profilindeki/sitesindeki mevcut fotoğrafları birlikte açıp güncelliğini sorarak başlayın ('{top_value}'); rakip profillerdeki görsellerle karşılaştırın.",
}

# Belirli bir kontrolün (ör. ele geçirilmiş site) kendine özgü satış cümleleri; genel şablon bunları yansıtamaz.
_KEY_OVERRIDES = {
    "spam_content": {
        "why": "Kayıtlı web sitesi işletmeyle ilgisiz, şüpheli (spam/yetişkin/bahis) içerik gösteriyor — site ele geçirilmiş olabilir; müşteri güveni ve Google sıralaması ciddi risk altında.",
        "pitch": "Kayıtlı web adresinizde işletmenizle ilgisiz, şüpheli içerik görünüyor; site ele geçirilmiş olabilir. Bu durum güveninizi ve Google sıralamanızı olumsuz etkiler — acil temizlik ve yeni bir kurumsal site önerebiliriz.",
        "talk": "Görüşmeye aciliyetle başlayın: sitenin şu anda gösterdiği içeriği ('{top_value}') işletme sahibiyle birlikte açıp görün; ardından güvenli, kurumsal bir yeniden kurulum önerin.",
    },
    "access": {
        "why": "Kayıtlı web sitesi açılmıyor ({top_value}); Google'dan gelen potansiyel müşteriler siteye ulaşamıyor olabilir.",
        "pitch": "Kayıtlı web siteniz şu anda açılmıyor; Google'dan ve kayıtlardan size gelmek isteyen potansiyel müşteriler siteye ulaşamıyor olabilir.",
        "talk": "Görüşmeye 'Web siteniz şu anda açılmıyor, haberiniz var mı?' sorusuyla başlayın; adresi birlikte tarayıcıda deneyin ve yeni/yenilenmiş bir site önerin.",
    },
    "brand_match": {
        "why": "Kayıtlı web sitesi adresi işletme adıyla uyumlu içerik göstermiyor; işletmenin gerçek sitesi olmayabilir.",
        "pitch": "Kayıtlı web adresinizde işletmenizle uyumlu bir içerik görünmüyor; doğru ve kurumsal bir web sitesiyle Google'da kendinizi net biçimde gösterebilirsiniz.",
        "talk": "Kayıtlı web adresini birlikte açın ve işletmenin gerçek sitesini sorun; yoksa kurumsal bir site kurulumuna geçin.",
    },
}

_EVENT_SECTORS = {"Düğün ve Davet Salonu", "Organizasyon ve Etkinlik", "Fotoğraf ve Video Stüdyosu", "Restoran", "Otel", "Bungalov ve Tatil Köyü"}
_FLEET_SECTORS = {
    "Nakliyat", "Kargo ve Kurye", "Taksi ve Transfer", "Lojistik ve Depolama", "Oto Kiralama", "Temizlik Şirketi", "Tesisat ve Isıtma-Soğutma",
    "Elektrik Taahhüt", "Peyzaj ve Fidanlık", "İnşaat Firması", "Toptan Ticaret", "Cam ve Doğrama",
}
_VISUAL_GROUPS = {"Yeme-İçme", "Konaklama ve Turizm", "Güzellik ve Kişisel Bakım", "Sağlık ve Tıp", "Ev, Mobilya ve Dekorasyon", "Perakende ve Mağazacılık"}

_POSSIBLE_BASIS = {
    SVC_ADS: "Sektörde yerel arama talebi yüksek; işletmenin Google Ads kullanıp kullanmadığı doğrulanamadı.",
    SVC_SIGN: "Fiziksel mekânı olan bir sektör; tabela/dış cephe görünürlüğü yerinde doğrulanmalı.",
    SVC_PRINT: "Bu sektörde {print_need} ihtiyacı olabilir; işletmenin mevcut basılı materyalleri doğrulanmadı.",
    SVC_SOCIAL_ADS: "İşletmenin doğrulanmış sosyal medya hesabı var; ancak reklam kullanıp kullanmadığı doğrulanamadı.",
    "Davetiye": "Düğün/etkinlik/organizasyon yapan bir sektör; davetiye ve basılı etkinlik materyali ihtiyacı olabilir, doğrulanamadı.",
    "Araç Giydirme": "Araç filosu/servis aracı kullanan bir sektör olabilir; işletmenin aracı olup olmadığı doğrulanamadı.",
    "Branda Baskı": "Fiziksel mekânı olan bir sektör; kampanya/duyuru için branda-afiş ihtiyacı yerinde doğrulanmalı.",
    "Promosyon Ürünleri": "Tekrar eden müşterisi olan bir sektör; logolu promosyon ürünü ihtiyacı doğrulanamadı.",
    SVC_MEDIA: "Görsel etkisi yüksek bir sektör; güncel profesyonel fotoğraf/video ihtiyacı görüşmede doğrulanmalı.",
    SVC_BRAND: "Logo/kurumsal kimlik ve basılı materyallerin tutarlılığı doğrulanamadı; görüşmede sorulmalı.",
}


def _compute_possible_services(ctx: AnalysisContext, evidenced: set[str], has_website: bool) -> list[dict]:
    """Kanıtı olmayan, sektör mantığına dayalı OLASI ihtiyaçlar. Seviyeyi etkilemez; ekranda ayrı ve 'doğrulama gerekir' olarak gösterilir."""
    possible: list[dict] = []
    if ctx.profile.local_intent and has_website and SVC_ADS not in evidenced:
        possible.append({"service": SVC_ADS, "basis": _POSSIBLE_BASIS[SVC_ADS]})
    if ctx.profile.storefront and SVC_SIGN not in evidenced:
        possible.append({"service": SVC_SIGN, "basis": _POSSIBLE_BASIS[SVC_SIGN]})
    if any(acc["status"] == "dogrulandi" and acc["network"] in ("instagram", "facebook") for acc in ctx.social) and SVC_SOCIAL_ADS not in evidenced:
        possible.append({"service": SVC_SOCIAL_ADS, "basis": _POSSIBLE_BASIS[SVC_SOCIAL_ADS]})
    if SVC_PRINT not in evidenced:
        possible.append({"service": SVC_PRINT, "basis": _POSSIBLE_BASIS[SVC_PRINT].format(print_need=ctx.profile.print_need)})
    group = getattr(ctx, "sector_group", None)
    if ctx.sector_name in _EVENT_SECTORS:
        possible.append({"service": "Davetiye", "basis": _POSSIBLE_BASIS["Davetiye"]})
    if ctx.sector_name in _FLEET_SECTORS:
        possible.append({"service": "Araç Giydirme", "basis": _POSSIBLE_BASIS["Araç Giydirme"]})
    if ctx.profile.storefront:
        possible.append({"service": "Branda Baskı", "basis": _POSSIBLE_BASIS["Branda Baskı"]})
    if group in _VISUAL_GROUPS and SVC_MEDIA not in evidenced:
        possible.append({"service": SVC_MEDIA, "basis": _POSSIBLE_BASIS[SVC_MEDIA]})
    if group in {"Yeme-İçme", "Perakende ve Mağazacılık", "Güzellik ve Kişisel Bakım", "Sağlık ve Tıp"}:
        possible.append({"service": "Promosyon Ürünleri", "basis": _POSSIBLE_BASIS["Promosyon Ürünleri"]})
    if SVC_BRAND not in evidenced:
        possible.append({"service": SVC_BRAND, "basis": _POSSIBLE_BASIS[SVC_BRAND]})
    return possible[:8]


def assess(ctx: AnalysisContext, checks: list[Check], *, has_website: bool, contactable_phone: bool, contactable_email: bool, conflicts: list[dict] | None = None) -> Assessment:
    problems = [c for c in checks if c.status == "problem"]
    scoring_problems = [c for c in problems if SEVERITY_WEIGHT.get(c.severity, 0) > 0]
    strengths = [c for c in checks if c.status == "ok"]
    gaps = sorted(scoring_problems, key=lambda c: (-_weight(c), _service_rank(c.services[0]) if c.services else 99))

    # ---- hizmet bazlı puanlar
    by_service: dict[str, ServiceOpportunity] = {}
    for check in scoring_problems:
        for service in check.services:
            entry = by_service.setdefault(service, ServiceOpportunity(service=service, points=0.0))
            entry.points = min(PER_SERVICE_CAP, entry.points + _weight(check))
            entry.problems.append(check)
    # Sıralama: önce EN GÜÇLÜ tekil kanıt (ör. web sitesi yok, site ele geçirilmiş), eşitlikte temel hizmetler
    # (sıra listesi), sonra toplam puan. Böylece çok sayıda küçük bulgu, asıl büyük eksiğin önüne geçmez.
    services = sorted(
        by_service.values(),
        key=lambda s: (-round(max(_weight(c) for c in s.problems), 2), _service_rank(s.service), -s.points),
    )
    services = [s for s in services if s.points >= 0.75]

    low_points = sum(_weight(c) for c in scoring_problems if c.severity == "low")
    total_points = sum(_weight(c) for c in scoring_problems if c.severity != "low") + min(low_points, LOW_POINTS_CAP)
    strong = [c for c in scoring_problems if c.severity in ("high", "medium") and c.confidence == "high"]
    strong_high = [c for c in strong if c.severity == "high"]
    verified_strong = bool(strong)
    # Seviye zaten doğrulanmış (güveni yüksek) güçlü bir bulguya dayanıyorsa "doğrulama gerekli" denmez.
    needs_verification = (not verified_strong) and any(c.needs_verification for c in scoring_problems)
    closed = next((c for c in problems if c.key == "business_status"), None)

    # ---- seviye
    if closed is not None:
        level, level_reason = "Düşük", f"{closed.value}; satış hedefi olmayabilir, önce doğrulayın."
    elif not scoring_problems:
        if any(c.status == "ok" and c.key not in ("presence",) for c in checks):
            level, level_reason = "Düşük", "Ölçülen alanlarda somut bir eksik tespit edilmedi; güçlü dijital varlığı olan bir işletme."
        else:
            level, level_reason = "Belirsiz", "Değerlendirme için yeterli doğrulanmış veri toplanamadı (site analiz edilemedi veya veri yok); manuel kontrol önerilir."
    elif (
        total_points >= HIGH_LEVEL_POINTS_ANY
        or (strong_high and total_points >= HIGH_LEVEL_POINTS_ONE_STRONG_HIGH)
        or (len(strong) >= 2 and total_points >= HIGH_LEVEL_POINTS_TWO_STRONG)
    ):
        level = "Yüksek"
    elif total_points >= MEDIUM_LEVEL_MIN_POINTS:
        level = "Orta"
    else:
        level = "Düşük"

    shorts: list[str] = []
    for check in gaps:
        if check.short and check.short not in shorts:
            shorts.append(check.short)
    if level in ("Yüksek", "Orta", "Düşük") and closed is None and scoring_problems:
        level_reason = _cap_first(" + ".join(shorts[:3])) + "."
        if level == "Düşük":
            level_reason += " (Tespit edilen eksikler küçük ölçekli.)"
    if needs_verification and level in ("Yüksek", "Orta") and closed is None:
        level_reason += " Doğrulama gerekli: bu bulgu tek başına kesin değil, görüşmeden önce kontrol edin."

    # ---- sıralama puanı (sadece iç kullanım): ihtiyaç puanı + ulaşılabilirlik
    rank_score = round(total_points + (1.5 if contactable_phone else 0) + (0.5 if contactable_email else 0), 2)
    if level == "Düşük":
        rank_score = min(rank_score, 1.9)
    elif level == "Belirsiz":
        rank_score = 0.0

    # ---- hizmet cümleleri
    primary = services[0] if services and level in ("Yüksek", "Orta") else None
    top_opportunity = why_call = talking_point = None
    values = {"phrase": ctx.main_phrase, "place": ctx.place, "name": ctx.business_name}

    if primary is not None:
        top_problem = max(primary.problems, key=_weight)
        top_opportunity = f"{primary.service} — {top_problem.value}"
        values.update({"issues": _issue_text(primary), "top_value": top_problem.value})
        override = _KEY_OVERRIDES.get(top_problem.key)
        why_call = (override["why"] if override else _WHY_TEMPLATES.get(primary.service, "{issues} tespit edildi.")).format(**values)
        talking_point = (override["talk"] if override else _TALKING_POINTS.get(primary.service, "Tespit edilen en somut eksiği ('{top_value}') birlikte inceleyerek başlayın.")).format(**values)
        pitch = (override["pitch"] if override else _PITCH_TEMPLATES.get(primary.service, "{issues} nedeniyle iyileştirilebilecek alanlar bulunuyor.")).format(**values)
        follow = f" Önce {primary.service}, ardından {services[1].service} önerilebilir." if len(services) > 1 else f" Önerilen ilk hizmet: {primary.service}."
        sales_note = pitch + follow
    elif level == "Düşük" and scoring_problems:
        why_call = "Tespit edilen eksikler küçük ölçekli; şimdilik öncelikli aday değil, ilgi gösterirse küçük bir iyileştirme paketi önerilebilir."
        talking_point = "Öncelikli bir satış noktası yok; başka fırsatlar için sıra bekleyebilir."
        sales_note = "Ölçülen alanlarda büyük bir eksik yok; öncelikli müşteriler bittikten sonra değerlendirin."
    elif level == "Düşük":
        why_call = "Ölçülen alanlarda somut bir eksik bulunamadı; güçlü dijital varlığı olan bir işletmeye satış gerekçesi zayıf."
        talking_point = "Somut bir satış noktası yok; bu işletmeyi listede aşağıda tutun."
        sales_note = "Web sitesi ve profil ölçümlerinde belirgin bir eksik tespit edilmedi."
    else:
        why_call = level_reason
        talking_point = "Önce işletmenin sitesini/profilini elle kontrol edin; ölçülemeyen alanlar için 'Doğrulanamadı' kayıtlarına bakın."
        sales_note = "Otomatik analiz yeterli veri toplayamadı; manuel inceleme gerekiyor."

    if closed is not None:
        why_call, talking_point, sales_note = level_reason, "Görüşmeden önce işletmenin açık olup olmadığını doğrulayın.", level_reason

    # ---- doğrulama adımları
    steps: list[str] = []
    if any(c.key == "presence" and c.status == "problem" and c.needs_verification for c in checks):
        steps.append(f"Google'da '{ctx.business_name} {ctx.place}' aratıp işletmenin gerçekten web sitesi olup olmadığını kontrol edin.")
    if any(c.key == "access" and c.status == "unknown" for c in checks):
        steps.append("Web sitesini tarayıcıda açıp elle inceleyin (otomatik erişim mümkün olmadı).")
    for conflict in conflicts or []:
        values = "; ".join(f"{src['label']}: {src['value']}" for src in conflict.get("sources", []))
        steps.append(f"{conflict['label']} — kaynaklar ÇELİŞKİLİ ({values}). Görüşmeden önce manuel kontrol edin.")
    if not ctx.is_google_data:
        google_status = ctx.source_status("google_maps")
        reason = f" ({google_status['detail']})" if google_status else ""
        steps.append("Google Haritalar'da işletme profilini açıp puan, yorum sayısı, fotoğraf ve kategori bilgilerini elle kontrol edin — Google İşletme Profili otomatik okunamadı" + reason + ".")

    evidenced = {s.service for s in services}
    possible = _compute_possible_services(ctx, evidenced, has_website) if level in ("Yüksek", "Orta", "Düşük") and closed is None else []
    possible = [p for i, p in enumerate(possible) if p["service"] not in evidenced and p["service"] not in {q["service"] for q in possible[:i]}]

    return Assessment(
        level=level, level_reason=level_reason, rank_score=rank_score, needs_verification=needs_verification,
        services=services, possible_services=possible, top_opportunity=top_opportunity, why_call=why_call,
        talking_point=talking_point, sales_note=sales_note, verification_steps=steps, gaps=gaps, strengths=strengths,
    )


def maps_search_url(name: str, address: str | None, place: str) -> str:
    query = f"{name} {address or place}".strip()
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"
