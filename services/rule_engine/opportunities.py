"""'Mchttasarım Satış Fırsatları': hizmet bazlı fırsat kartları.

İki grup ayrı tutulur (varsayım ile tespit karıştırılmaz):
- TESPİTE DAYALI: analizde bulunan gerçek sorunlara bağlı hizmetler. Her kartta seviye, tespit edilen sorun(lar) + kanıt, neden önerildiği,
  satış gerekçesi ve sunulabilecek hizmet bulunur.
- SEKTÖRE DAYALI OLASILIKLAR: kanıtı olmayan, sektörün doğasından çıkan olası ihtiyaçlar. Sorun alanında açıkça "Tespit edilmedi" yazar ve
  seviye "Doğrulanmadı"dır.
"""

from services.knowledge.guides import SERVICE_TO_GUIDE, guide_for_check
from services.rule_engine.sales import CONFIDENCE_FACTOR, SEVERITY_WEIGHT, Assessment

# Satış gerekçesi (kanıtla birlikte gösterilir; kesin sonuç iddiası içermez)
RATIONALE = {
    "Kurumsal Web Sitesi": "Doğrulanmış bir web sitesi olmadığında Google'da arama yapan müşteri işletmenin hizmetlerine ve iletişim bilgilerine kendi sayfasından ulaşamıyor olabilir; kurumsal site bu boşluğu kapatır ve diğer dijital çalışmaların temelini oluşturur.",
    "Web Tasarım": "Mevcut sitede tespit edilen eksikler ziyaretçinin iletişime geçmeden ayrılmasına yol açabilir; tasarım/yapı düzeltmesi siteyi müşteri kazandıran bir araca dönüştürür.",
    "E-Ticaret": "Ürün satan işletmenin online satış kanalı bulunmadığında mağaza dışındaki talep kaçabilir; e-ticaret bu talebi karşılayabilir.",
    "Kurumsal SEO": "Sayfa içi ve teknik eksikler, sitenin Google'da hizmet aramalarında görünmesini zorlaştırıyor olabilir; düzeltme organik (ücretsiz) görünürlüğü destekler.",
    "Yerel SEO": "Şehir/ilçe odaklı aramalarda ('hizmet + bölge') bölgesel görünürlük eksikliği, yakındaki hazır müşterinin rakibe gitmesine yol açabilir.",
    "Google İşletme Profili Optimizasyonu": "Google Haritalar aramalarında güven ve görünürlüğü doğrudan profilin doluluğu, yorumları ve fotoğrafları etkiler; eksikler rakiplerin gerisinde kalmaya neden olabilir.",
    "Sosyal Medya Yönetimi": "Doğrulanabilir bir sosyal medya varlığı bulunmadığında marka güveni ve tekrar müşteri fırsatı kullanılmıyor olabilir.",
    "Fotoğraf ve Video İçerik": "Güncel ve kaliteli görsel eksikliği, profil ve sitede tıklamayı ve güveni azaltabilir.",
    "Grafik Tasarım": "Görsel eksikler işletmenin profesyonellik algısını etkileyebilir.",
}
OFFER = {
    "Kurumsal Web Sitesi": "Kurumsal web sitesi + yerel SEO altyapısı",
    "Web Tasarım": "Web sitesi yenileme / iyileştirme",
    "E-Ticaret": "E-ticaret sitesi kurulumu",
    "Kurumsal SEO": "Kurumsal SEO (sayfa içi + teknik düzenleme)",
    "Yerel SEO": "Yerel SEO paketi",
    "Google İşletme Profili Optimizasyonu": "Google İşletme Profili optimizasyonu",
    "Sosyal Medya Yönetimi": "Sosyal medya yönetimi",
    "Fotoğraf ve Video İçerik": "Profesyonel fotoğraf/video çekimi",
    "Grafik Tasarım": "Grafik tasarım",
}
POSSIBLE_RATIONALE = "Bu, sektörün doğasından çıkan OLASI bir ihtiyaçtır; işletmede böyle bir sorun tespit edilmemiştir. Görüşmede sorularak doğrulanmalıdır."


def _level(problems_weight: float, max_weight: float) -> str:
    if max_weight >= 2.25 or problems_weight >= 5:
        return "Yüksek"
    if problems_weight >= 2 or max_weight >= 1.5:
        return "Orta"
    return "Düşük"


def _weight(check: dict) -> float:
    return SEVERITY_WEIGHT.get(check["severity"], 0) * CONFIDENCE_FACTOR.get(check["confidence"], 0.4)


def build_opportunities(assessment: Assessment) -> dict:
    """Döndürür: {"evidence": [...], "possible": [...]} (payload'a kaydedilir)."""
    evidence: list[dict] = []
    for opportunity in assessment.services:
        problems = []
        weights = []
        for check in sorted(opportunity.problems, key=lambda c: -(SEVERITY_WEIGHT.get(c.severity, 0) * CONFIDENCE_FACTOR.get(c.confidence, 0.4))):
            guide = guide_for_check(check.area, check.key)
            problems.append({
                "label": check.value, "evidence": check.detail, "severity": check.severity, "confidence": check.confidence,
                "needs_verification": check.needs_verification, "check_key": check.key, "area": check.area, "guide_id": guide.id if guide else None,
            })
            weights.append(SEVERITY_WEIGHT.get(check.severity, 0) * CONFIDENCE_FACTOR.get(check.confidence, 0.4))
        top = opportunity.problems and max(opportunity.problems, key=lambda c: SEVERITY_WEIGHT.get(c.severity, 0) * CONFIDENCE_FACTOR.get(c.confidence, 0.4))
        evidence.append({
            "service": opportunity.service,
            "level": _level(sum(weights), max(weights) if weights else 0),
            "verified": True,
            "problems": problems[:5],
            "why": (top.why if top else "") or "",
            "rationale": RATIONALE.get(opportunity.service, "Tespit edilen eksikler bu hizmetle giderilebilir."),
            "offer": OFFER.get(opportunity.service, opportunity.service),
            "primary": bool(evidence == [] and assessment.top_opportunity),
            "fallback_guide_id": SERVICE_TO_GUIDE.get(opportunity.service),
        })

    possible = [
        {
            "service": p["service"], "level": "Doğrulanmadı", "verified": False, "problems": [],
            "problem_text": "Tespit edilmedi — sektöre dayalı olası ihtiyaç.", "why": p["basis"], "rationale": POSSIBLE_RATIONALE,
            "offer": OFFER.get(p["service"], p["service"]), "guide_id": SERVICE_TO_GUIDE.get(p["service"]),
        }
        for p in assessment.possible_services
    ]
    return {"evidence": evidence, "possible": possible}
