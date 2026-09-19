"""OpenStreetMap/Overpass artık işletme arama akışında KULLANILMAZ — kod tabanında iz kalmamalı ve varsayılan sağlayıcı Google Haritalar olmalı."""

from pathlib import Path

import pytest

from packages.config import Settings

ROOT = Path(__file__).resolve().parent.parent
CODE_DIRS = ["services", "apps/api", "packages"]
ALLOWED_LEGACY = ("osm_overpass",)  # veritabanında kalmış eski kayıtların discovery_source değeri (yalnızca okunur)


def _python_files():
    for directory in CODE_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            if "migrations" in path.parts or "__pycache__" in path.parts:
                continue
            yield path


def test_no_overpass_endpoint_or_module_in_code():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("overpass-api.de", "overpass.kumi", "overpass_provider", "overpassprovider", "/api/interpreter", "nwr[", "[out:json]"):
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}: {needle}")
    assert not offenders, offenders


def test_overpass_provider_file_is_gone():
    assert not (ROOT / "services/integrations/google_places/overpass_provider.py").exists()


def test_default_provider_is_google_maps_and_legacy_osm_value_is_mapped():
    assert Settings(discovery_provider="osm").discovery_provider == "google_maps"
    assert Settings(discovery_provider="Overpass").discovery_provider == "google_maps"
    assert Settings(discovery_provider="google_maps").discovery_provider == "google_maps"


def test_factory_returns_google_maps_provider(monkeypatch, db):
    from packages.config import settings
    from services.integrations.google_places.factory import get_places_provider
    from services.integrations.google_places.maps_provider import GoogleMapsProvider

    monkeypatch.setattr(settings, "discovery_provider", "google_maps")
    assert isinstance(get_places_provider(db), GoogleMapsProvider)


def test_factory_rejects_unknown_provider(monkeypatch, db):
    from packages.config import settings
    from services.integrations.google_places.factory import get_places_provider

    monkeypatch.setattr(settings, "discovery_provider", "overpass-typo")
    with pytest.raises(ValueError):
        get_places_provider(db)


def test_health_reports_google_maps_as_real_source(client, monkeypatch):
    from packages.config import settings

    monkeypatch.setattr(settings, "discovery_provider", "google_maps")
    body = client.get("/api/health").json()
    assert body["discovery_provider"] == "google_maps" and body["is_real_data_source"] is True
