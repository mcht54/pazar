"""GooglePlacesProvider'ı gerçek ağ çağrısı yapmadan (httpx.post mock'lanarak) test eder."""

from packages.db.models import Region, Sector
from services.integrations.google_places import google_provider as gp_module
from services.integrations.google_places.google_provider import GooglePlacesProvider

FAKE_PAGE_1 = {
    "places": [
        {
            "id": "abc123",
            "displayName": {"text": "Gerçek Güzellik Salonu"},
            "formattedAddress": "Test Mah. Test Cad. No:1, Serdivan/Sakarya",
            "location": {"latitude": 40.76, "longitude": 30.34},
            "nationalPhoneNumber": "(0264) 000 00 00",
            "websiteUri": "https://example.com",
            "rating": 4.5,
            "userRatingCount": 120,
            "regularOpeningHours": {"weekdayDescriptions": ["Monday: 9:00 AM - 6:00 PM"]},
            "businessStatus": "OPERATIONAL",
            "types": ["beauty_salon"],
        }
    ],
    "nextPageToken": "TOKEN_PAGE_2",
}
FAKE_PAGE_2 = {
    "places": [
        {
            "id": "def456",
            "displayName": {"text": "İkinci Salon"},
            "formattedAddress": "Başka Cadde No:2, Serdivan/Sakarya",
            "location": {"latitude": 40.77, "longitude": 30.35},
        }
    ]
}


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def test_google_provider_paginates_and_parses(seeded_db, monkeypatch):
    settings_key_holder = {"calls": 0}

    def fake_post(url, json, headers, timeout):
        settings_key_holder["calls"] += 1
        assert headers["X-Goog-Api-Key"] == "fake-test-key"
        assert "places.rating" in headers["X-Goog-FieldMask"]
        if "pageToken" not in json:
            return _FakeResponse(FAKE_PAGE_1)
        assert json["pageToken"] == "TOKEN_PAGE_2"
        return _FakeResponse(FAKE_PAGE_2)

    monkeypatch.setattr(gp_module.httpx, "post", fake_post)
    monkeypatch.setattr(gp_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(gp_module.settings, "google_places_api_key", "fake-test-key")

    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Güzellik Salonu").one()

    outcome = GooglePlacesProvider(seeded_db).search(region=region, sector=sector, target_count=2)

    assert outcome.provider_name == "google_places"
    assert outcome.is_demo_data is False
    assert len(outcome.items) == 2
    assert settings_key_holder["calls"] == 2  # iki sayfa çağrıldı

    first = outcome.items[0]
    assert first.external_ref == "google_abc123"
    assert first.name == "Gerçek Güzellik Salonu"
    assert first.rating == 4.5
    assert first.review_count == 120
    assert first.opening_hours == "Monday: 9:00 AM - 6:00 PM"


def test_google_provider_stops_at_target_count(seeded_db, monkeypatch):
    monkeypatch.setattr(gp_module.httpx, "post", lambda *a, **k: _FakeResponse(FAKE_PAGE_1))
    monkeypatch.setattr(gp_module.settings, "google_places_api_key", "fake-test-key")

    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Güzellik Salonu").one()

    outcome = GooglePlacesProvider(seeded_db).search(region=region, sector=sector, target_count=1)
    assert len(outcome.items) == 1


def test_google_provider_requires_api_key(seeded_db, monkeypatch):
    monkeypatch.setattr(gp_module.settings, "google_places_api_key", "")
    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Güzellik Salonu").one()

    try:
        GooglePlacesProvider(seeded_db).search(region=region, sector=sector, target_count=5)
        assert False, "GOOGLE_PLACES_API_KEY yokken açık bir hata fırlatılmalı"
    except RuntimeError as exc:
        assert "GOOGLE_PLACES_API_KEY" in str(exc)
