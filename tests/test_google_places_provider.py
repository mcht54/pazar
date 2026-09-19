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


def test_google_fieldmask_requests_profile_fields_but_not_unneeded_ones(seeded_db, monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen["mask"] = headers["X-Goog-FieldMask"]
        return _FakeResponse({"places": []})

    monkeypatch.setattr(gp_module.httpx, "post", fake_post)
    monkeypatch.setattr(gp_module.settings, "google_places_api_key", "fake-test-key")
    monkeypatch.setattr(gp_module.settings, "google_places_fetch_reviews", True)
    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Güzellik Salonu").one()
    GooglePlacesProvider(seeded_db).search(region=region, sector=sector, target_count=1)

    mask = seen["mask"]
    for needed in ("places.primaryTypeDisplayName", "places.googleMapsUri", "places.photos.name", "places.reviews.publishTime", "places.userRatingCount"):
        assert needed in mask
    assert "places.reviews.text" not in mask and "places.photos.authorAttributions" not in mask, "gereksiz (pahalı) alanlar istenmemeli"


def test_google_reviews_field_can_be_disabled(seeded_db, monkeypatch):
    monkeypatch.setattr(gp_module.settings, "google_places_fetch_reviews", False)
    assert "reviews" not in gp_module._field_mask()


def test_google_provider_parses_profile_fields(seeded_db, monkeypatch):
    place = {
        "id": "xyz",
        "displayName": {"text": "Profil Salonu"},
        "formattedAddress": "Adres",
        "location": {"latitude": 40.7, "longitude": 30.3},
        "types": ["beauty_salon", "point_of_interest"],
        "primaryType": "beauty_salon",
        "primaryTypeDisplayName": {"text": "Güzellik salonu"},
        "googleMapsUri": "https://maps.google.com/?cid=123",
        "photos": [{"name": f"p{i}"} for i in range(10)],
        "reviews": [{"publishTime": "2026-05-01T10:00:00Z"}, {"publishTime": "2026-08-20T09:30:00Z"}],
        "businessStatus": "OPERATIONAL",
    }
    monkeypatch.setattr(gp_module.httpx, "post", lambda *a, **k: _FakeResponse({"places": [place]}))
    monkeypatch.setattr(gp_module.settings, "google_places_api_key", "fake-test-key")
    monkeypatch.setattr(gp_module.settings, "google_places_fetch_reviews", True)
    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Güzellik Salonu").one()

    item = GooglePlacesProvider(seeded_db).search(region=region, sector=sector, target_count=1).items[0]

    assert item.category_label == "Güzellik salonu"
    assert item.maps_url == "https://maps.google.com/?cid=123"
    assert item.photo_count == 10 and item.photos_capped is True, "10 fotoğraf API üst sınırıdır: gerçek sayı 'en az 10'"
    assert item.last_review_at.date().isoformat() == "2026-08-20", "en yeni yorum tarihi seçilmeli"
    assert item.reviews_sampled == 2
    assert item.profile["primary_type"] == "beauty_salon"
    # Google'ın vermediği alanlar uydurulmaz:
    assert item.rating is None and item.review_count is None and item.phone is None and item.website is None


def test_google_provider_does_not_invent_photo_count_when_field_absent(seeded_db, monkeypatch):
    place = {"id": "nophoto", "displayName": {"text": "Fotoğrafsız"}, "location": {"latitude": 1, "longitude": 1}}
    monkeypatch.setattr(gp_module.httpx, "post", lambda *a, **k: _FakeResponse({"places": [place]}))
    monkeypatch.setattr(gp_module.settings, "google_places_api_key", "fake-test-key")
    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Güzellik Salonu").one()
    item = GooglePlacesProvider(seeded_db).search(region=region, sector=sector, target_count=1).items[0]
    # Places yanıtında "photos" hiç yoksa Google gerçekten fotoğraf döndürmemiştir (0); reviews yoksa tarih bilinmez (None).
    assert item.photo_count == 0
    assert item.last_review_at is None
