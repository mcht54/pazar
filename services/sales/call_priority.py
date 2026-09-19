"""🔥 "Bugün Kimi Aramalıyım?" — SATIŞ ÖNCELİK PUANI (0-100) ve "Neden bugün aranmalı?" gerekçesi.

Bu puan "satış fırsatı skoru"ndan FARKLIDIR: skor firmanın dijital eksiklerini ölçer; bu puan bugün kimi aramanın en verimli olacağını sıralar.
Her bileşen gerçek veriden gelir; veri yoksa bileşen 0 puan alır ve gerekçede "doğrulanamadı" denir (uydurma yok).

Bileşenler (ağırlık):
  gerçek fırsat (öncelik değeri) 30 · aciliyet (doğrulanmış yüksek önemli bulgu) 10 · hizmet uyumu / ticari değer 10 · ticari yapı (yorum sayısı) 8 ·
  dijital durum (web/Google/sosyal alanlarında doğrulanmış eksik) 8 · rakipten kazanma 4 · iletişim bilgisi 8 · CRM/takip durumu 22
  (geciken/bugünkü takip, ulaşılamadı, teklif bekleyen, önceki görüşme sonucu, ilk arama).
Elenenler: kapanmış (Kazanıldı/Kaybedildi), takip tarihi ileri olan, bugün zaten ulaşılmış, kamu/rakip/kendisi.
"""

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")

W = {"opportunity": 30, "urgency": 10, "service_fit": 10, "commercial": 8, "digital": 8, "competitor": 4, "contact": 8, "crm": 22}
CLOSED = ("Kazanıldı", "Kaybedildi")
# durum → (bileşen puanı 0-1, gerekçe)  — takip tarihi yokken durumun kendisi
STAGE_WEIGHT = {
    "Takip Bekliyor": (0.45, "Takip bekliyor: tarihi girilmemiş, kontrol edilmeli"),
    "Görüşüldü": (0.55, "Görüşüldü; teklif aşamasına taşınmalı"),
    "Teklif Gönderildi": (0.5, "Teklif gönderildi; yanıt/karar için takip edilmeli"),
    "Arandı": (0.35, "Arandı; sonuç/sonraki adım netleştirilmeli"),
    "Aranacak": (0.3, "Aranacak listesinde"),
    "Yeni": (0.2, "Yeni kayıt: henüz aranmamış"),
    "Daha Sonra Ara": (0.1, "Daha sonra aranacak olarak işaretlenmiş (tarih girilmemiş)"),
}


def _local_date(value: datetime):
    return value.astimezone(TZ).date()


def score_call(*, priority_value: float | None, matrix: dict | None, has_phone: bool, has_email: bool, mobile_phone: bool, review_count: int | None,
               provider_wins: int, crm_stage: str | None, in_crm: bool, follow_state: str | None, follow_at: datetime | None,
               last_contact_at: datetime | None, call_attempts: int, now: datetime | None = None) -> dict:
    """Döndürür: {"excluded": str|None, "score": float, "reasons": [str], "components": {...}, "next_action": str}"""
    now = now or datetime.now(timezone.utc)
    reasons: list[tuple[float, str]] = []
    comp: dict[str, float] = {}

    if in_crm and crm_stage in CLOSED:
        return {"excluded": f"CRM durumu “{crm_stage}” — kapanmış kayıt", "score": 0.0, "reasons": [], "components": {}, "next_action": ""}
    if follow_state == "upcoming":
        return {"excluded": f"Takip tarihi ileri ({_local_date(follow_at).strftime('%d.%m.%Y')})", "score": 0.0, "reasons": [], "components": {}, "next_action": ""}
    contacted_today = last_contact_at is not None and _local_date(last_contact_at) == _local_date(now)
    if contacted_today and follow_state not in ("overdue", "today"):
        return {"excluded": "Bugün zaten görüşüldü", "score": 0.0, "reasons": [], "components": {}, "next_action": ""}

    items = (matrix or {}).get("items", [])
    greens = [i for i in items if i["level"] == "satis"]
    yellows = [i for i in items if i["level"] == "olasi" and not i["sector_only"]]

    # 1) gerçek fırsat
    pv = float(priority_value) if priority_value is not None else 0.0
    comp["opportunity"] = W["opportunity"] * max(0.0, min(pv, 100.0)) / 100
    if priority_value is not None:
        reasons.append((comp["opportunity"], f"Satış öncelik değeri {pv:.0f}/100" + (f"; {len(greens)} hizmette doğrulanmış fırsat" if greens else "")))
    else:
        reasons.append((0.0, "Analiz yok — fırsat değeri doğrulanamadı"))

    # 2) aciliyet: doğrulanmış YÜKSEK önemli bulgular
    high = [e for i in greens for e in i["evidence"] if e.get("verified") and e.get("severity") == "high"]
    comp["urgency"] = W["urgency"] * min(1.0, len(high) / 2)
    if high:
        reasons.append((comp["urgency"], "Acil sayılabilecek doğrulanmış bulgu: " + high[0]["text"]))

    # 3) hizmet uyumu / ticari değer (en iyi 🟢/kanıtlı 🟡 hizmet)
    best = max((i["commercial"] * (1.15 if i["recurring"] else 1.0) for i in greens + yellows), default=0.0)
    comp["service_fit"] = W["service_fit"] * min(1.0, best / 5)
    if best:
        top = max(greens + yellows, key=lambda i: i["commercial"] * (1.15 if i["recurring"] else 1.0))
        reasons.append((comp["service_fit"], f"Hizmet uyumu: {top['service']}" + (" (tekrar eden gelir)" if top["recurring"] else "")))

    # 4) ticari yapı: yorum sayısı işletmenin aktif olduğunu gösterir (yoksa doğrulanamadı)
    if review_count is not None and review_count > 0:
        comp["commercial"] = W["commercial"] * min(1.0, math.log10(review_count + 1) / 2)  # 100 yorumda tam puan
        reasons.append((comp["commercial"], f"Google’da {review_count} yorum — faal bir işletme"))
    else:
        comp["commercial"] = 0.0

    # 5) dijital durum: web/Google/sosyal alanlarında doğrulanmış eksik
    areas = {e["area"] for i in greens + yellows for e in i["evidence"] if e.get("verified") and e["area"] in ("website", "gbp", "social")}
    comp["digital"] = W["digital"] * min(1.0, len(areas) / 3)
    if areas:
        labels = {"website": "web sitesi", "gbp": "Google profili", "social": "sosyal medya"}
        reasons.append((comp["digital"], "Doğrulanmış eksik: " + ", ".join(labels[a] for a in sorted(areas))))

    # 6) rakipten kazanma
    comp["competitor"] = W["competitor"] if provider_wins else 0.0
    if provider_wins:
        reasons.append((comp["competitor"], "Mevcut sağlayıcı kanıtı + doğrulanmış eksik: rakipten kazanma fırsatı"))

    # 7) iletişim bilgisi
    contact = (0.6 if has_phone else 0.0) + (0.2 if has_email else 0.0) + (0.2 if mobile_phone else 0.0)
    comp["contact"] = W["contact"] * contact
    reasons.append((comp["contact"], "Telefon mevcut" + (", e-posta mevcut" if has_email else "") + (", cep numarası (WhatsApp deneyebilir)" if mobile_phone else "")
                    if has_phone else "Telefon doğrulanamadı — ulaşılabilirlik düşük"))

    # 8) CRM / takip durumu
    crm_points, crm_reason, action = 0.0, None, "İlk aramayı yap ve sonucu CRM'e işle"
    if follow_state == "overdue":
        crm_points, crm_reason, action = 1.0, f"Gecikmiş takip ({_local_date(follow_at).strftime('%d.%m.%Y')})", "Gecikmiş takibi tamamla"
    elif follow_state == "today":
        crm_points, crm_reason, action = 0.85, "Bugün takip günü", "Bugünkü takibi tamamla"
    elif in_crm and crm_stage in STAGE_WEIGHT:
        crm_points, crm_reason = STAGE_WEIGHT[crm_stage]
        action = {"Teklif Gönderildi": "Teklif geri dönüşünü sor", "Görüşüldü": "Teklif için bir sonraki adımı planla",
                  "Arandı": "Sonraki adımı belirle ve takip tarihi gir"}.get(crm_stage, "Ara ve sonucu CRM'e işle")
    elif not in_crm:
        crm_points, crm_reason = 0.18, "CRM'e alınmamış yeni fırsat"
        action = "Ara; ilgi varsa CRM'e ekle"
    if follow_state is None and last_contact_at is None and call_attempts and call_attempts >= 3:
        crm_points *= 0.5
        reasons.append((0.0, f"{call_attempts} kez denendi ama görüşme gerçekleşmedi — ısrar yerine başka kanal (WhatsApp/e-posta) düşünün"))
    if call_attempts == 0 and crm_points:
        crm_points = min(1.0, crm_points + 0.1)
    comp["crm"] = W["crm"] * crm_points
    if crm_reason:
        reasons.append((comp["crm"], crm_reason))
    if call_attempts:
        reasons.append((0.0, f"Önceki arama denemesi: {call_attempts}"))
    else:
        reasons.append((0.0, "Daha önce aranmamış"))

    score = round(max(0.0, min(100.0, sum(comp.values()))), 1)
    reasons.sort(key=lambda r: -r[0])
    return {"excluded": None, "score": score, "reasons": [r for _, r in reasons], "components": {k: round(v, 1) for k, v in comp.items()},
            "weights": W, "next_action": action}
