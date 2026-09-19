"""Mevcut sağlayıcı / rakip sinyalleri ("Bu firma zaten bir ajansla mı çalışıyor?").

KURALLAR
- Yalnızca GÖRÜLEN kanıt raporlanır (sayfa altı kredisi, reklam/ölçüm etiketi, hazır platform). Kanıt yoksa durum "Doğrulanamadı" olur; "ajansı yok" ASLA denmez.
- "Rakipten kazanma fırsatı" ancak (1) mevcut bir sağlayıcı kanıtı VE (2) o hizmet alanında doğrulanmış bir eksik birlikte varsa gösterilir.
  Mevcut sağlayıcının işinin kalitesi ya da müşterinin memnuniyeti hakkında YARGI VERİLMEZ; bu görüşmede sorulacak bir konu olarak sunulur.
- Her sinyalin kaynağı belirtilir (Website / Google / Social).
"""

from sqlalchemy.orm import Session

from packages.db.models import BusinessMetric

UNVERIFIED = "Doğrulanamadı"

# kategori anahtarı → (başlık, ilgili Mchttasarım hizmetleri)
CATEGORIES = {
    "web": ("Web sitesi sağlayıcısı", ["Kurumsal Web Sitesi", "Web Tasarım"]),
    "social": ("Sosyal medya yönetimi", ["Sosyal Medya Yönetimi", "Sosyal Medya İçerik Üretimi"]),
    "seo": ("SEO sağlayıcısı", ["Kurumsal SEO", "Yerel SEO"]),
    "ads": ("Reklam altyapısı / yönetimi", ["Google Ads", "Sosyal Medya Reklamları"]),
    "print": ("Logo / matbaa / baskı sağlayıcısı", ["Logo Tasarımı", "Matbaa", "Kurumsal Kimlik"]),
}

PLATFORM_GENERATORS = ("wordpress", "wix", "shopify", "squarespace", "webflow", "joomla", "drupal", "opencart", "prestashop", "woocommerce", "elementor")


def latest_site_signals(db: Session, business_id: int) -> dict | None:
    row = (
        db.query(BusinessMetric)
        .filter(BusinessMetric.business_id == business_id, BusinessMetric.metric_key == "website.signals", BusinessMetric.status == "known")
        .order_by(BusinessMetric.id.desc()).first()
    )
    return row.value if row else None


def _matrix_level(matrix: dict | None, service: str) -> str | None:
    for item in (matrix or {}).get("items", []):
        if item["service"] == service:
            return item["level"]
    return None


def build_provider_signals(signals: dict | None, matrix: dict | None, *, has_website: bool, social_verified: int = 0) -> dict:
    """Beş kategori için durum: {"items": [...], "win_opportunities": [...]}. Her kategori tespit edildi ya da 'Doğrulanamadı' olur."""
    signals = signals or {}
    items: dict[str, dict] = {k: {"key": k, "title": t, "status": "dogrulanamadi", "status_label": UNVERIFIED, "value": None, "evidence": None, "source": None, "url": None}
                              for k, (t, _) in CATEGORIES.items()}
    credit = signals.get("agency_credit")
    generator = (signals.get("generator") or "").lower()

    web = items["web"]
    if credit and credit.get("kind") == "agency":
        web.update(status="tespit_edildi", status_label="Tespit edildi", value=credit.get("name"), evidence=f"Sayfa altı kredisi: “{credit.get('text')}”",
                   source="Website", url=credit.get("url"))
    elif credit and credit.get("kind") == "platform":
        web.update(status="platform", status_label="Hazır platform", value=credit.get("name"), evidence=f"Sayfa altı kredisi: “{credit.get('text')}”", source="Website", url=credit.get("url"))
    elif any(p in generator for p in PLATFORM_GENERATORS):
        web.update(status="platform", status_label="Hazır platform / tema", value=signals.get("generator"), evidence=f"Sayfada “{signals.get('generator')}” üretici etiketi görüldü (ajans bilgisi değildir).", source="Website")
    elif not has_website:
        web.update(status="yok", status_label="Web sitesi yok", evidence="İşletmenin doğrulanmış bir web sitesi bulunmadı.", source="Website")
    elif signals and signals.get("success") is False:
        web.update(evidence="Web sitesi okunamadığı için ölçülemedi.", source="Website")
    elif signals:
        web.update(evidence="Sayfa altında ajans/geliştirici kredisi görülmedi (bu, ajans olmadığı anlamına gelmez).", source="Website")

    ads = items["ads"]
    tools = signals.get("analytics_tools")
    if tools is not None:
        found = [t for t in tools if t in ("google_ads", "meta_pixel")]
        labels = {"google_ads": "Google Ads dönüşüm etiketi", "meta_pixel": "Meta (Facebook/Instagram) Pixel"}
        if found:
            ads.update(status="tespit_edildi", status_label="Reklam etiketi görüldü", value=", ".join(labels[t] for t in found),
                       evidence="Ana sayfa HTML'inde " + ", ".join(labels[t] for t in found) + " görüldü. Reklamı kimin yönettiği bilinmiyor.", source="Website")
        else:
            ads.update(evidence="Ana sayfada reklam etiketi görülmedi (görünmeyen bir etiketin yokluğu kesin değildir).", source="Website")

    social = items["social"]
    if social_verified:
        social.update(evidence=f"{social_verified} doğrulanmış sosyal medya hesabı var; hesapların kim tarafından yönetildiği doğrulanamadı.", source="Social")

    # SEO ve logo/matbaa sağlayıcısı sayfa/profil verisinden anlaşılamaz → 'Doğrulanamadı'
    items["seo"].update(evidence="SEO çalışmasını kimin yaptığı sayfa verisinden anlaşılamaz.")
    items["print"].update(evidence="Logo/matbaa sağlayıcısı dijital verilerden anlaşılamaz.")

    wins = []
    if web["status"] == "tespit_edildi":
        for svc in CATEGORIES["web"][1]:
            if _matrix_level(matrix, svc) == "satis":
                wins.append({
                    "service": svc, "provider": web["value"], "source": "Website",
                    "text": f"Rakipten kazanma fırsatı: web sitesi başka bir sağlayıcıyla yapılmış görünüyor ({web['value']}) ve {svc} alanında doğrulanmış eksikler var. "
                            "Mevcut sağlayıcıdan memnuniyet ve geçiş isteği görüşmede sorulmalı; sağlayıcının işi hakkında yargı verilmez.",
                })
                break
    if ads["status"] == "tespit_edildi" and signals.get("cta_present") is False and _matrix_level(matrix, "Google Ads") in ("satis", "olasi"):
        wins.append({
            "service": "Google Ads", "provider": None, "source": "Website",
            "text": "Reklam etiketi var ama sitede belirgin harekete geçirici çağrı görülmedi: reklam trafiğinin dönüşüme çevrilmesi konusunda iyileştirme önerilebilir "
                    "(mevcut reklam yöneticisi bilinmiyor; görüşmede sorulmalı).",
        })
    return {"items": list(items.values()), "win_opportunities": wins}
