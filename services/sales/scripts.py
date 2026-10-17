"""Kişiselleştirilmiş satış metinleri: telefon konuşması, WhatsApp, e-posta taslağı, kısa not.

KURALLAR (dürüstlük)
- Metinlerde GERÇEK olgu olarak yalnızca doğrulanmış (verified) analiz bulguları geçer; bunlar "inceleme notu" diliyle ("… bulunamadı") yazılır.
- Doğrulanmamış ya da yalnızca sektöre dayalı çıkarımlar olguymuş gibi yazılmaz; SORU olarak sorulur ("… konusunda destek ister misiniz?").
- Rakip/mevcut sağlayıcı hakkında yargı verilmez; fiyat vaadi yoktur; sonuç garantisi verilmez.
- Kullanılan olgular `facts_used` ile ayrıca döndürülür, böylece personel neyin kanıta dayandığını görür.
"""

MAX_FACTS = 2
MARKAKARNEM_URL = "https://markakarnem.com.tr"


def markakarnem_link(business_name: str, place: str | None) -> str:
    """İşletmenin adıyla doldurulmuş MarkaKarnem analiz bağlantısı (açılınca işletme kendiliğinden aranır; k=pazar kaynağı sayar).
    Türkçe harfler olduğu gibi bırakılır (WhatsApp ve tarayıcılar destekler); boşluk "+" olur, URL'yi bozan işaretler atılır."""
    q = " ".join(f"{business_name} {place or ''}".translate({ord(c): " " for c in "&#?%+/=\\"}).split())
    return f"{MARKAKARNEM_URL}/analiz?q={q.replace(' ', '+')}&k=pazar"


def markakarnem_text(business_name: str, place: str | None) -> str:
    """Mesajlara eklenen MarkaKarnem tanıtımı. Ücretsizdir; sonuç ya da sıralama vaadi içermez."""
    return ("Ayrıca işletmenizin dijital karnesini 1 dakikada ücretsiz görebilirsiniz: web siteniz, Google profiliniz ve Instagram'ınız "
            "52 kontrolle ölçülür, yakınınızdaki rakiplerle kıyaslanır. Kart bilgisi gerekmez.\n"
            f"👉 {markakarnem_link(business_name, place)}")


def _verified_facts(matrix: dict | None, limit: int = MAX_FACTS) -> list[dict]:
    """En güçlü doğrulanmış bulgular (önce 🟢 hizmetler): [{"service","text","detail"}]."""
    facts: list[dict] = []
    for item in (matrix or {}).get("items", []):
        if item["level"] != "satis":
            continue
        ev = next((e for e in item["evidence"] if e.get("verified")), None)
        if ev and all(f["detail"] != ev["detail"] for f in facts):
            facts.append({"service": item["service"], "text": ev["text"], "detail": ev["detail"] or ev["text"]})
        if len(facts) >= limit:
            break
    return facts


def _possible_services(matrix: dict | None, limit: int = 2) -> list[str]:
    return [i["service"] for i in (matrix or {}).get("items", []) if i["level"] in ("satis", "olasi")][:limit]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ve " + items[-1]


def build_scripts(*, business_name: str, sector_name: str | None, place: str | None, matrix: dict | None, staff_name: str | None,
                  company: str = "Mchttasarım", provider_wins: list[dict] | None = None) -> dict:
    facts = _verified_facts(matrix)
    services = _possible_services(matrix)
    me = staff_name or "satış ekibi"
    where = f" ({place})" if place else ""
    sector = f" {sector_name.lower()}" if sector_name else ""
    services_text = _join(services) if services else "dijital görünürlük"

    if facts:
        finding_lines = [f"• {f['detail']}" for f in facts]
        opener_fact = f"Kısa bir inceleme yaptık: {facts[0]['detail']}"
        basis = "kanıta dayalı"
    else:
        finding_lines = []
        opener_fact = None
        basis = "genel (doğrulanmış bulgu yok)"

    # --- telefon konuşması
    call = [f"Merhaba, ben {me}, {company} ekibindenim. {business_name}{where} ile mi görüşüyorum?"]
    if opener_fact:
        call.append(f"{opener_fact}")
        call.append(f"Bu konuda {services_text} tarafında size somut bir iyileştirme önerebiliriz; 5 dakikanızı alabilir miyim?")
    else:
        call.append(f"Size uygun olabilecek {services_text} konusunda kısa bir sorum var: bu alanda şu an destek alıyor musunuz?")
    call.append("Cevabınız ‘hayır’ ise: Nazikçe teşekkür edip yeniden aranmasını isteyip istemediğini sorun; ısrar etmeyin.")
    if provider_wins:
        call.append("Mevcut bir sağlayıcıyla çalışıyorlarsa: memnuniyetlerini ve gelecekte alternatif değerlendirmeye açık olup olmadıklarını sorun (sağlayıcı hakkında olumsuz konuşmayın).")

    # --- WhatsApp
    wa = f"Merhaba, ben {me}, {company} ekibindenim. {business_name} için kısa bir dijital inceleme yaptık."
    if facts:
        wa += f" {facts[0]['detail']} Bu konuda ücretsiz kısa bir görüşme yapmak ister misiniz?"
    else:
        wa += f" {services_text} konusunda destek almayı düşünür müsünüz? Uygunsanız kısa bir görüşme planlayabiliriz."
    karne = markakarnem_text(business_name, place)
    wa += "\n\n" + karne

    # --- e-posta
    body = ["Merhaba,", "", f"Ben {me}, {company} ekibindenim. {business_name}{where} için genel bir dijital inceleme yaptık."]
    if finding_lines:
        body += ["", "İncelemede öne çıkan noktalar:", *finding_lines]
        body += ["", f"Bu konularda {services_text} alanında somut öneriler hazırlayabiliriz."]
    else:
        body += ["", f"{services_text.capitalize()} konusunda işletmenize uygun olabilecek çalışmalarımızı paylaşmak isteriz. Bu alanda şu an destek alıp almadığınızı öğrenmek isteriz."]
    body += ["", "Uygun bir zamanda kısa bir görüşme yapabilir miyiz?", "", karne, "", "İyi çalışmalar,", me, company]
    email = {"subject": f"{business_name} için dijital inceleme notlarımız" if facts else f"{business_name} — {services_text} hakkında", "body": "\n".join(body)}

    # --- kısa not (personel içi)
    note = f"{business_name}: " + ("; ".join(f["text"] for f in facts) if facts else "doğrulanmış bulgu yok") + f". Önerilen: {services_text}."
    return {
        "call": "\n".join(call), "whatsapp": wa, "email": email, "short_note": note,
        "facts_used": facts, "basis": basis,
        "markakarnem": {"text": karne, "link": markakarnem_link(business_name, place), "image": "/markakarnem-kare.jpg"},
        "caveat": "Metinlerde yalnızca doğrulanmış bulgular olgu olarak geçer; gönderiminden önce kontrol edin ve gerekirse kendi üslubunuza uyarlayın.",
    }
