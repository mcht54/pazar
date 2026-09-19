"""Potansiyel müşteri ÖNCELİK sıralaması: yalnızca skora güvenmez.

öncelik = 0.50·skor + 0.20·fırsat sayısı + 0.22·ticari anlamlılık + 0.08·analiz tamamlanma

Örnek: skor 90 ama yalnızca küçük bir teknik eksik (tek hizmet, düşük ticari değer) → yaklaşık 64;
       skor 82 ama Mchttasarım'ın üç farklı hizmetini (web + SEO + Ads) satma ihtimali → yaklaşık 89. Yani ikincisi üstte çıkar.
Neden üstte olduğu `reasons` ile kullanıcıya gösterilir. Her bileşen gerçek analiz bulgularından gelir.
"""

W_SCORE, W_COUNT, W_COMMERCIAL, W_COMPLETE = 0.50, 0.20, 0.22, 0.08


def compute_priority(*, score: int, matrix: dict, completeness: float, has_phone: bool) -> dict:
    items = matrix["items"]
    greens = [i for i in items if i["level"] == "satis"]
    yellows_ev = [i for i in items if i["level"] == "olasi" and not i["sector_only"]]
    yellows_sector = [i for i in items if i["level"] == "olasi" and i["sector_only"]]

    count_c = min(100.0, 34 * len(greens) + 10 * len(yellows_ev) + 3 * len(yellows_sector))
    commercial_c = min(100.0, sum(g["commercial"] * (1.3 if g["recurring"] else 1.0) * 8 for g in greens)
                       + sum(y["commercial"] * (1.3 if y["recurring"] else 1.0) * 2.4 for y in yellows_ev))
    complete_c = max(0.0, min(100.0, completeness * 100))
    value = W_SCORE * score + W_COUNT * count_c + W_COMMERCIAL * commercial_c + W_COMPLETE * complete_c
    if not has_phone:
        value -= 4  # aranamayan firma sıralamada hafifçe geride (satış ekibi için ulaşılabilirlik)
    value = round(max(0.0, min(100.0, value)), 1)

    reasons = [f"Satış fırsatı skoru {score}/100"]
    if greens:
        reasons.append(f"{len(greens)} hizmette doğrulanmış satış fırsatı: " + ", ".join(g["service"] for g in greens[:4]) + ("…" if len(greens) > 4 else ""))
    elif yellows_ev:
        reasons.append(f"Doğrulanmış hizmet fırsatı yok; kanıtlı {len(yellows_ev)} olası fırsat: " + ", ".join(y["service"] for y in yellows_ev[:3]))
    else:
        reasons.append("Doğrulanmış veya kanıtlı hizmet fırsatı tespit edilmedi; sıralama yalnızca sektöre dayalı olasılıklara bağlı")
    big = [g["service"] for g in greens if g["commercial"] >= 4]
    if big:
        reasons.append("Ticari değeri yüksek hizmet(ler): " + ", ".join(big[:3]) + (" (aylık tekrar eden gelir)" if any(g["recurring"] and g["commercial"] >= 4 for g in greens) else ""))
    reasons.append("Analiz eksiksiz — ölçülebilen alanların tamamı değerlendirildi" if completeness >= 0.8 else "Bazı alanlar doğrulanamadı; sıralama temkinli değerlendirilmeli")
    reasons.append("Telefon mevcut (ulaşılabilir)" if has_phone else "Telefon doğrulanamadı (ulaşılabilirlik düşük)")
    return {"value": value, "components": {"score": score, "opportunity_count": round(count_c, 1), "commercial": round(commercial_c, 1), "completeness": round(complete_c, 1)},
            "weights": {"score": W_SCORE, "opportunity_count": W_COUNT, "commercial": W_COMMERCIAL, "completeness": W_COMPLETE}, "reasons": reasons}


def why_prospect(matrix: dict, limit: int = 6) -> list[str]:
    """'🔥 Neden potansiyel müşteri?': yalnızca gerçek kanıta dayalı maddeler (önce 🟢, sonra kanıtlı 🟡). Kanıtsız sektör olasılıkları yazılmaz."""
    lines: list[str] = []
    for item in matrix["items"]:
        if item["level"] not in ("satis", "olasi") or not item["evidence"]:
            continue
        text = item["evidence"][0]["text"]
        line = f"{item['service']}: {text}" if item["evidence"][0].get("area") == "derived" else text
        if item["service"] == "Google Ads":
            line = "Google Ads fırsatı tespit edildi — " + text
        if line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines
