"""Aynı işletmenin tekrar tekrar 'yeni' görünmesini önleyen eşleştirme (ad + konum + telefon + Google Maps kaydı).

Şube ve benzer adlı komşu işletmeleri BİRLEŞTİRMEMEK için kurallar sıkıdır: aynı telefonu paylaşan iki şube (farklı adreslerde)
ayrı işletme sayılır; yalnızca aynı yerdeki (koordinat) kayıtlar aynı kabul edilir.
"""

from services.research.normalize import haversine_m, name_similarity, normalize_phone

SAME_PLACE_METERS = 60  # ad benzerse bu mesafede aynı yer
SAME_PHONE_METERS = 150  # aynı telefon + benzer ad + bu mesafede aynı işletme


def same_business(a: dict, b: dict) -> tuple[bool, str | None]:
    """a, b: {"name", "phone", "lat", "lng", "place_id"} — döndürür (aynı mı, gerekçe)."""
    if a.get("place_id") and a.get("place_id") == b.get("place_id"):
        return True, "Google Maps kaydı aynı"

    sim = name_similarity(a.get("name"), b.get("name"))
    distance = None
    if None not in (a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")):
        distance = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])

    if sim >= 0.85 and distance is not None and distance <= SAME_PLACE_METERS:
        return True, "Ad ve konum aynı"
    pa, pb = normalize_phone(a.get("phone")), normalize_phone(b.get("phone"))
    if pa and pa == pb and sim >= 0.8 and distance is not None and distance <= SAME_PHONE_METERS:
        return True, "Ad, telefon ve konum aynı"
    return False, None
