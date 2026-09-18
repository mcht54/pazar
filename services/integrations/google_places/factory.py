from sqlalchemy.orm import Session

from packages.config import settings
from services.integrations.google_places.base import PlacesProvider


def get_places_provider(db: Session) -> PlacesProvider:
    """DISCOVERY_PROVIDER ayarına göre provider döner. Varsayılan: osm (gerçek veri).

    DISCOVERY_PROVIDER=mock SADECE test/geliştirme içindir — normal kullanımda seçilmemeli.
    """
    provider_name = settings.discovery_provider.strip().lower()

    if provider_name == "osm":
        from services.integrations.google_places.overpass_provider import OverpassProvider

        return OverpassProvider()

    if provider_name == "mock":
        from services.integrations.google_places.mock_provider import MockPlacesProvider

        return MockPlacesProvider()

    if provider_name == "google":
        from services.integrations.google_places.google_provider import GooglePlacesProvider

        return GooglePlacesProvider(db)

    raise ValueError(f"Bilinmeyen DISCOVERY_PROVIDER: '{provider_name}' (osm | mock | google olmalı)")
