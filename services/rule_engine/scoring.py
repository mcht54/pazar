"""Satış fırsatı PUANI (0-100) — rastgele değil, gerçek tespitlere dayanır ve her puan kalemi açıklanır ("Neden bu puanı aldı?").

Hesap:
- Her SORUN kontrolü bir puan kalemidir: etki puanı × güven çarpanı (yüksek 1.0 / orta 0.75 / düşük 0.4).
  Etki puanı önem derecesinden gelir (yüksek 15 / orta 8 / düşük 3); bazı ağır tespitlerin sabit ağırlığı vardır
  (ör. web sitesi hiç yok = 40, site ele geçirilmiş = 35).
- Alan başına üst sınır vardır (web sitesi/SEO 60, Google profili 30, sosyal medya 12): tek bir alandaki çok sayıda küçük bulgu puanı şişirmesin.
- "Sektörel varsayımlar" (ör. Google Ads olasılığı) DOĞRULANMAMIŞTIR; toplamda en fazla 8 puan katkı verir ve ayrıca etiketlenir.
- "Doğrulanamadı" (ölçülemeyen) alanlar puana katkı VERMEZ.
Puan; tespit sayısı, önemi ve güvenilirliği artıkça yükselir; sorunsuz/güçlü bir işletmede düşük kalır.
"""

from services.rule_engine.checks import Check

SEVERITY_IMPACT = {"high": 15, "medium": 8, "low": 3, "none": 0}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.75, "low": 0.4}
# Ağır tespitler için sabit ağırlık ("<alan>.<anahtar>")
KEY_IMPACT = {
    "website.presence": 40,
    "website.spam_content": 35,
    "website.access": 30,
    "website.indexing": 25,
    "gbp.profile_found": 25,
    "website.conversion": 12,
    "website.brand_match": 12,
}
AREA_LABEL = {"website": "Web sitesi ve SEO", "gbp": "Google İşletme Profili", "social": "Sosyal medya"}
AREA_CAP = {"website": 60, "gbp": 30, "social": 12}
ASSUMPTION_CAP = 8
ASSUMPTION_POINTS = {"Google Ads": 4, "Sosyal Medya Reklamları": 2, "Tabela": 1, "Matbaa": 1, "Fotoğraf ve Video İçerik": 1, "Davetiye": 1, "Araç Giydirme": 1}
SEVERITY_TR = {"high": "yüksek", "medium": "orta", "low": "düşük"}
CONFIDENCE_TR = {"high": "yüksek", "medium": "orta", "low": "düşük"}


def band(score: int) -> str:
    """Puan bandı (kullanıcıya gösterilen fırsat seviyesi ifadesi)."""
    if score >= 70:
        return "Çok yüksek fırsat"
    if score >= 45:
        return "Yüksek fırsat"
    if score >= 20:
        return "Orta fırsat"
    return "Düşük fırsat"


def _impact(check: Check) -> float:
    base = KEY_IMPACT.get(f"{check.area}.{check.key}", SEVERITY_IMPACT.get(check.severity, 0))
    return base * CONFIDENCE_FACTOR.get(check.confidence, 0.4)


# Puan dökümü için gruplar: "+20 Web sitesi eksikleri, +15 Local SEO, +12 Google Ads fırsatı ..." — her puan gerçek bir bulguya bağlıdır.
_GROUP_BY_KEY = {
    "web.presence": "Web sitesi yok / erişilemiyor", "web.access": "Web sitesi yok / erişilemiyor",
    "web.local_seo": "Local SEO fırsatı", "web.title_keywords": "Local SEO fırsatı", "web.maps_link": "Local SEO fırsatı",
    "web.analytics": "Google Ads / ölçüm fırsatı",
    "web.conversion": "İletişim / dönüşüm eksikleri", "web.cta": "İletişim / dönüşüm eksikleri", "web.tel_link": "İletişim / dönüşüm eksikleri",
    "web.whatsapp": "İletişim / dönüşüm eksikleri", "web.booking": "İletişim / dönüşüm eksikleri",
    "web.title": "SEO eksikleri", "web.meta_description": "SEO eksikleri", "web.h1": "SEO eksikleri", "web.heading_structure": "SEO eksikleri",
    "web.content_volume": "SEO eksikleri", "web.schema": "SEO eksikleri", "web.indexing": "SEO eksikleri", "web.sitemap": "SEO eksikleri",
    "web.blog": "SEO eksikleri", "web.internal_links": "SEO eksikleri", "web.images": "SEO eksikleri",
    "web.social_links": "Sosyal medya fırsatı",
}
_GROUP_BY_AREA = {"gbp": "Google İşletme eksikleri", "social": "Sosyal medya fırsatı", "website": "Web sitesi eksikleri"}


def _group_of(check: Check) -> str:
    area = "web" if check.area == "website" else check.area
    return _GROUP_BY_KEY.get(f"{area}.{check.key}") or _GROUP_BY_AREA.get(check.area, "Diğer")


def compute_score(checks: list[Check], possible_services: list[dict]) -> dict:
    """Döndürür: {"score", "band", "items", "adjustments", "assumptions", "summary"}. Tüm kalemler kullanıcıya açıklama olarak gösterilir."""
    items: list[dict] = []
    by_area: dict[str, list[dict]] = {}
    for check in checks:
        if check.status != "problem" or check.severity == "none":
            continue
        points = round(_impact(check))
        if points <= 0:
            continue
        item = {
            "kind": "tespit",
            "area": check.area,
            "area_label": AREA_LABEL.get(check.area, check.area),
            "label": check.value,
            "points": points,
            "explanation": f"Önem: {SEVERITY_TR.get(check.severity, '-')}, güven: {CONFIDENCE_TR.get(check.confidence, '-')}"
            + (" · doğrulama gerekli" if check.needs_verification else ""),
            "services": list(check.services),
            "check_key": f"{'web' if check.area == 'website' else check.area}.{check.key}",
            "group": _group_of(check),
        }
        items.append(item)
        by_area.setdefault(check.area, []).append(item)

    items.sort(key=lambda i: -i["points"])
    adjustments: list[dict] = []
    total = 0
    for area, area_items in by_area.items():
        raw = sum(i["points"] for i in area_items)
        cap = AREA_CAP.get(area, 20)
        if raw > cap:
            adjustments.append({"label": f"{AREA_LABEL.get(area, area)}: alan üst sınırı ({cap}) uygulandı", "points": -(raw - cap)})
        total += min(raw, cap)

    assumptions: list[dict] = []
    raw_assumption = 0
    for possible in possible_services:
        pts = ASSUMPTION_POINTS.get(possible["service"], 0)
        if pts:
            assumptions.append({"kind": "varsayım", "label": f"{possible['service']} (sektöre dayalı olasılık — DOĞRULANMADI)", "points": pts, "explanation": possible["basis"]})
            raw_assumption += pts
    assumption_total = min(raw_assumption, ASSUMPTION_CAP)
    if raw_assumption > ASSUMPTION_CAP:
        adjustments.append({"label": f"Sektörel varsayımlar için üst sınır ({ASSUMPTION_CAP}) uygulandı", "points": -(raw_assumption - ASSUMPTION_CAP)})

    groups = _score_groups(by_area, assumption_total)
    score = max(0, min(100, total + assumption_total))
    if not items:
        summary = "Ölçülen alanlarda somut bir eksik tespit edilmedi; puan yalnızca sektörel (doğrulanmamış) olasılıklardan oluşuyor." if assumptions else "Ölçülen alanlarda somut bir eksik tespit edilmedi."
    else:
        summary = f"{len(items)} somut tespit puana katkı verdi (en büyük katkı: {items[0]['label']})."
    return {"score": score, "band": band(score), "groups": groups, "items": items, "adjustments": adjustments, "assumptions": assumptions, "summary": summary,
            "note": "Puan yalnızca tespit edilen (ve güven derecesiyle ağırlıklandırılan) eksiklere dayanır. 'Doğrulanamadı' olan alanlar puana katkı vermez."}


def _score_groups(by_area: dict[str, list[dict]], assumption_total: int) -> list[dict]:
    """Puanı gruplara böler (alan üst sınırı uygulanmış haliyle); gruplar toplamı = tespit puanı + sınırlanmış varsayım puanı."""
    weights: dict[str, float] = {}
    target = 0
    for area, area_items in by_area.items():
        raw = sum(i["points"] for i in area_items)
        capped = min(raw, AREA_CAP.get(area, 20))
        target += capped
        ratio = capped / raw if raw else 0
        for item in area_items:
            weights[item["group"]] = weights.get(item["group"], 0.0) + item["points"] * ratio
    floors = {g: int(w) for g, w in weights.items()}
    remainder = target - sum(floors.values())
    for g in sorted(weights, key=lambda g: weights[g] - floors[g], reverse=True)[: max(0, remainder)]:
        floors[g] += 1
    groups = [{"label": g, "points": p} for g, p in floors.items() if p > 0]
    groups.sort(key=lambda x: -x["points"])
    if assumption_total:
        groups.append({"label": "Sektörel varsayımlar (doğrulanmamış)", "points": assumption_total})
    return groups
