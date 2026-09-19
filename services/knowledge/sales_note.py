"""'Satış Notu Oluştur': gerçek analiz sonuçlarından personelin görüşmede kullanacağı kısa not. Uydurma bilgi içermez; her cümle
analizde bulunan bir tespite veya doğrulanamayan bir alana dayanır."""

from services.knowledge.guides import GUIDES, guide_for_check


def build_sales_note(business, payload: dict, *, sector: str, place: str, phrase: str, level: str, primary: str | None, secondary: str | None,
                     talking_point: str | None, sales_pitch: str | None) -> dict:
    gaps = payload.get("gaps", [])[:3]
    opportunities = (payload.get("opportunities") or {}).get("evidence", [])
    top = opportunities[0] if opportunities else None

    problems = [{"problem": g["value"], "evidence": g.get("detail") or "", "verified": not g.get("needs_verification")} for g in gaps]
    why_service = (top or {}).get("why") or ""
    rationale = (top or {}).get("rationale") or ""

    # görüşmede sorulabilecek sorular: ilgili rehberlerden (tekrarsız, en fazla 5)
    questions: list[str] = []
    for gap in gaps:
        guide = guide_for_check(gap["area"], gap["key"])
        if guide:
            for q in guide.questions:
                q = q.replace("{isletme}", business.name).replace("{sehir}", place).replace("{kelime}", phrase).replace("{sektor}", sector)
                if q not in questions:
                    questions.append(q)
    questions = questions[:5]

    unverified = [c["label"] for c in (payload.get("gbp") or {}).get("checks", []) if c["status"] == "unknown"][:4]
    caveats = []
    if not (payload.get("gbp") or {}).get("available"):
        caveats.append("Google İşletme Profili verisi okunamadı; profil bilgileri Doğrulanamadı.")
    elif unverified:
        caveats.append("Google'ın vermediği/okunamayan alanlar (Doğrulanamadı): " + ", ".join(unverified) + ".")
    for step in payload.get("verification_steps", [])[:3]:
        caveats.append(step)

    lines = [f"SATIŞ NOTU — {business.name} ({sector}, {place})", f"Satış fırsatı: {level}"]
    if business.phone:
        lines.append(f"Telefon: {business.phone}")
    lines.append("")
    if problems:
        lines.append("TESPİT EDİLEN PROBLEMLER (analizde ölçülen):")
        lines += [f"- {p['problem']}" + ("" if p["verified"] else " (doğrulama gerekli)") for p in problems]
    else:
        lines.append("TESPİT EDİLEN PROBLEM: Somut bir eksik tespit edilmedi.")
    if primary:
        lines += ["", f"ÖNERİLEN HİZMET: {primary}" + (f" (ikinci: {secondary})" if secondary else "")]
        if why_service:
            lines.append(f"Neden bu hizmet: {why_service}")
        elif rationale:
            lines.append(f"Neden bu hizmet: {rationale}")
    if sales_pitch:
        lines += ["", "MÜŞTERİYE SÖYLENEBİLECEK KISA AÇIKLAMA:", sales_pitch]
    if talking_point:
        lines += ["", "GÖRÜŞMEYE NASIL BAŞLANIR:", talking_point]
    if questions:
        lines += ["", "GÖRÜŞMEDE SORULABİLECEK SORULAR:"] + [f"- {q}" for q in questions]
    if caveats:
        lines += ["", "GÖRÜŞMEDEN ÖNCE KONTROL EDİN:"] + [f"- {c}" for c in caveats]
    return {
        "business": business.name, "sector": sector, "place": place, "level": level, "phone": business.phone,
        "problems": problems, "primary_service": primary, "secondary_service": secondary, "why_service": why_service or rationale,
        "pitch": sales_pitch, "talking_point": talking_point, "questions": questions, "caveats": caveats, "text": "\n".join(lines),
    }
