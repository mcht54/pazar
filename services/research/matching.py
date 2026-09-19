"""İşletme eşleştirme: bir dizin kaydı (Google/Bing) gerçekten ARANAN işletme mi?

Yanlış işletmenin bilgisini bağlamamak için kabul koşulu sıkıdır: skor eşiği + en az İKİ bağımsız olumlu sinyal
(ad, konum, telefon, adres). Tek başına benzer bir isim (örn. başka bir "… İşitme Cihazları") yeterli değildir.
"""

from services.research.models import BusinessQuery, MatchInfo
from services.research.normalize import (
    address_overlap,
    haversine_m,
    name_similarity,
    normalize_phone,
)

ACCEPT_SCORE = 0.7
MIN_POSITIVE_SIGNALS = 2


def score_match(
    query: BusinessQuery,
    *,
    name: str | None,
    lat: float | None = None,
    lng: float | None = None,
    phone: str | None = None,
    address: str | None = None,
    website: str | None = None,
) -> MatchInfo:
    signals: list[str] = []
    negatives: list[str] = []
    score = 0.0
    positives = 0

    sim = name_similarity(query.name, name, query.extra_generic)
    if sim >= 0.8:
        score += 0.45
        positives += 1
        signals.append(f"Ad eşleşti (%{round(sim * 100)})")
    elif sim >= 0.5:
        score += 0.25
        signals.append(f"Ad kısmen benziyor (%{round(sim * 100)})")
    else:
        negatives.append(f"Ad farklı (%{round(sim * 100)})")
        score -= 0.2

    distance = None
    if None not in (query.lat, query.lng, lat, lng):
        distance = round(haversine_m(query.lat, query.lng, lat, lng))
        if distance <= 75:
            score += 0.35
            positives += 1
            signals.append(f"Konum aynı ({distance} m fark)")
        elif distance <= 250:
            score += 0.25
            positives += 1
            signals.append(f"Konum yakın ({distance} m fark)")
        elif distance <= 600:
            score += 0.1
            signals.append(f"Konum aynı mahallede ({distance} m fark)")
        elif distance > 1500:
            score -= 0.4
            negatives.append(f"Konum uzak ({distance} m fark)")

    candidate_phone = normalize_phone(phone)
    if candidate_phone and query.phones:
        if candidate_phone in query.phones:
            score += 0.4
            positives += 1
            signals.append("Telefon eşleşti")
        else:
            score -= 0.15
            negatives.append("Telefon farklı")

    overlap = address_overlap(query.address, address, exclude=query.extra_generic)
    if overlap is not None:
        if overlap >= 0.6:
            score += 0.2
            positives += 1
            signals.append(f"Adres eşleşti (%{round(overlap * 100)})")
        elif overlap < 0.2:
            score -= 0.1
            negatives.append("Adres farklı")

    accepted = score >= ACCEPT_SCORE and positives >= MIN_POSITIVE_SIGNALS
    return MatchInfo(accepted=accepted, score=round(score, 2), signals=signals, negatives=negatives,
                     distance_m=distance, name_similarity=sim)
