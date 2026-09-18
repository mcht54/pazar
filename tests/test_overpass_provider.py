"""OverpassProvider'ı gerçek ağ çağrısı yapmadan (httpx.post mock'lanarak) test eder."""

from packages.db.models import Region, Sector
from services.integrations.google_places import overpass_provider as op_module
from services.integrations.google_places.overpass_provider import OverpassProvider, _build_query

FAKE_OVERPASS_RESPONSE = {
    "elements": [
        {
            "type": "node",
            "id": 111,
            "lat": 40.76,
            "lon": 30.34,
            "tags": {
                "amenity": "restaurant",
                "name": "Gerçek Restoran A",
                "addr:street": "Test Caddesi",
                "addr:housenumber": "5",
                "addr:district": "Serdivan",
                "phone": "+90 264 000 00 00",
                "website": "https://example.com",
                "opening_hours": "Mo-Su 09:00-22:00",
            },
        },
        {
            "type": "way",
            "id": 222,
            "center": {"lat": 40.77, "lon": 30.35},
            "tags": {"shop": "bakery", "name": "Gerçek Fırın B"},
        },
        {
            # İsimsiz kayıt — kullanılabilir bir işletme değil, atlanmalı
            "type": "node",
            "id": 333,
            "lat": 40.75,
            "lon": 30.33,
            "tags": {"amenity": "restaurant"},
        },
        {
            # Aynı node tekrar (Overpass bazen union'da tekrar edebilir) — dedup edilmeli
            "type": "node",
            "id": 111,
            "lat": 40.76,
            "lon": 30.34,
            "tags": {"amenity": "restaurant", "name": "Gerçek Restoran A"},
        },
    ]
}


class _FakeResponse:
    status_code = 200

    def json(self):
        return FAKE_OVERPASS_RESPONSE


def test_build_query_includes_tags_and_keywords():
    query = _build_query(40.76, 30.34, 7000, ["amenity=restaurant"], ["restoran", "lokanta"])
    assert 'node["amenity"="restaurant"](around:7000,40.76,30.34);' in query
    assert 'name"~"restoran|lokanta"' in query


def test_overpass_provider_parses_real_looking_response(seeded_db, monkeypatch):
    monkeypatch.setattr(op_module.httpx, "post", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(op_module, "_throttle", lambda: None)

    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Restoran").one()

    outcome = OverpassProvider().search(region=region, sector=sector, target_count=10)

    assert outcome.is_demo_data is False
    assert outcome.provider_name == "osm_overpass"
    names = [i.name for i in outcome.items]
    assert "Gerçek Restoran A" in names
    assert "Gerçek Fırın B" in names
    assert len(names) == 2, "İsimsiz kayıt atlanmalı, tekrar eden node dedup edilmeli"

    restoran_a = next(i for i in outcome.items if i.name == "Gerçek Restoran A")
    assert restoran_a.external_ref == "osm_node_111"
    assert restoran_a.address is not None and "Test Caddesi" in restoran_a.address
    assert restoran_a.phone == "+90 264 000 00 00"
    assert restoran_a.website == "https://example.com"
    assert restoran_a.opening_hours == "Mo-Su 09:00-22:00"
    assert restoran_a.rating is None  # OSM'de rating yok — asla uydurulmaz
    assert restoran_a.review_count is None


def test_overpass_provider_caps_at_target_count(seeded_db, monkeypatch):
    monkeypatch.setattr(op_module.httpx, "post", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(op_module, "_throttle", lambda: None)

    region = seeded_db.query(Region).filter_by(name="Serdivan").one()
    sector = seeded_db.query(Sector).filter_by(name="Restoran").one()

    outcome = OverpassProvider().search(region=region, sector=sector, target_count=1)
    assert len(outcome.items) == 1
