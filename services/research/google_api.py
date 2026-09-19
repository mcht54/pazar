"""Google Places API (New) — TAMAMLAYICI kaynak.

Bu modül mevcut kaynakların (Google Haritalar okuma, Bing Haritalar, resmi web sitesi) YERİNE GEÇMEZ; yalnızca yönetici API'yi
aktifleştirdiyse ek bir bağımsız kaynak olarak eklenir. Amaç: mevcut bilgileri çapraz doğrulamak, eksik alanları tamamlamak ve çelişkileri
göstermek. Başarısız olursa (anahtar/kota/ağ) hata fırlatılır; pipeline bunu "ERİŞİLEMEDİ" olarak kaydeder ve mevcut kaynaklarla
DEVAM EDER. Google'ın vermediği alan None kalır — hiçbir değer tahmin edilmez.
"""

import httpx

from packages.config import settings

from services.research.browser import SourceError
from services.research.matching import score_match
from services.research.models import BusinessQuery, DirectoryProfile

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
TIMEOUT = 10.0
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.location", "places.nationalPhoneNumber", "places.websiteUri",
    "places.rating", "places.userRatingCount", "places.regularOpeningHours.weekdayDescriptions", "places.primaryTypeDisplayName",
    "places.googleMapsUri", "places.editorialSummary", "places.businessStatus",
])
SOURCE = "google_api"


def _post(body: dict, api_key: str) -> dict:
    """Tek HTTP çağrısı (testlerde değiştirilir)."""
    response = httpx.post(settings.google_places_search_url, json=body, headers={"Content-Type": "application/json", "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}, timeout=TIMEOUT)
    if response.status_code != 200:
        raise SourceError(SOURCE, f"Google API HTTP {response.status_code} döndürdü ({response.text[:120]})")
    return response.json()


def _profile(place: dict) -> DirectoryProfile:
    loc = place.get("location") or {}
    hours = (place.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
    display = place.get("displayName") or {}
    return DirectoryProfile(
        source=SOURCE, name=display.get("text"), url=place.get("googleMapsUri"), place_id=place.get("id"),
        lat=loc.get("latitude"), lng=loc.get("longitude"), rating=place.get("rating"), review_count=place.get("userRatingCount"),
        category=(place.get("primaryTypeDisplayName") or {}).get("text"), address=place.get("formattedAddress"),
        phone=place.get("nationalPhoneNumber"), website=place.get("websiteUri"), hours_text=" | ".join(hours) if hours else None,
        hours=[{"day": h.split(": ", 1)[0], "hours": h.split(": ", 1)[1]} for h in hours if ": " in h],
        description=(place.get("editorialSummary") or {}).get("text"),
    )


def lookup(query: BusinessQuery, api_key: str) -> tuple[DirectoryProfile | None, str]:
    """İşletmeyi Places API ile arar; GÜVENLE eşleşen kayıt varsa profil döner (eşleşme kuralları Google Haritalar ile aynıdır)."""
    text = f"{query.name} {' '.join(query.place_names)}".strip()
    body: dict = {"textQuery": text, "pageSize": 5, "languageCode": "tr", "regionCode": "TR"}
    if query.lat is not None and query.lng is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": query.lat, "longitude": query.lng}, "radius": 1500.0}}
    try:
        data = _post(body, api_key)
    except httpx.RequestError as exc:
        raise SourceError(SOURCE, f"Google API'ye ulaşılamadı ({type(exc).__name__})") from exc
    best: tuple[float, DirectoryProfile] | None = None
    for place in data.get("places") or []:
        profile = _profile(place)
        info = score_match(query, name=profile.name, lat=profile.lat, lng=profile.lng, phone=profile.phone, address=profile.address, website=profile.website)
        profile.match = info
        if info.accepted and (best is None or info.score > best[0]):
            best = (info.score, profile)
    if best is None:
        return None, "Google API'de işletmeyle güvenle eşleşen kayıt bulunamadı."
    profile = best[1]
    return profile, "Google API kaydı işletmeyle eşleştirildi: " + ", ".join(profile.match.signals) + "."


# Google Haritalar profili varken API'den TAMAMLANAN alanlar. Telefon/adres/web sitesi/ad burada YOKTUR: onlar bağımsız kaynak olarak
# çapraz doğrulamaya girer (aynı değeri iki kez sayıp sahte "doğrulandı" üretmemek için).
COMPLEMENT_FIELDS = ("rating", "review_count", "category", "hours_text", "hours", "description")


def merge_into_maps(maps: DirectoryProfile, api: DirectoryProfile) -> dict[str, str]:
    """Maps profilindeki BOŞ alanları API'den tamamlar (mevcut değerin üzerine yazmaz). Döndürür: {alan: "google_api"} — hangi alan API'den geldi."""
    filled: dict[str, str] = {}
    for name in COMPLEMENT_FIELDS:
        current, extra = getattr(maps, name), getattr(api, name)
        if (current in (None, "", [])) and extra not in (None, "", []):
            setattr(maps, name, extra)
            filled[name] = SOURCE
    return filled
