from sqlalchemy.orm import Session

from packages.config import settings
from services.integrations.google_places.base import PlacesProvider


def get_places_provider(db: Session) -> PlacesProvider:
    """DISCOVERY_PROVIDER ayarına göre keşif sağlayıcısı. Varsayılan: google_maps (anahtarsız, gerçek Google Haritalar verisi).

    google_maps -> Google Haritalar (tarayıcıyla, API anahtarı gerekmez)
    google      -> Google Places API (New) — GOOGLE_PLACES_API_KEY gerekir
    mock        -> SADECE testler için sahte veri
    (Eski 'osm' değeri Overpass artık kullanılmadığı için config katmanında 'google_maps'e çevrilir.)
    """
    provider_name = settings.discovery_provider.strip().lower()

    if provider_name == "google_maps":
        from services.integrations.google_places.maps_provider import GoogleMapsProvider

        return GoogleMapsProvider()

    if provider_name == "mock":
        from services.integrations.google_places.mock_provider import MockPlacesProvider

        return MockPlacesProvider()

    if provider_name == "google":
        from services.integrations.google_places.google_provider import GooglePlacesProvider

        return GooglePlacesProvider(db)

    raise ValueError(f"Bilinmeyen DISCOVERY_PROVIDER: '{provider_name}' (google_maps | google | mock olmalı)")
