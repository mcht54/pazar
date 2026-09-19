"""Google Haritalar keşif sağlayıcısı: sonuç kartı ayrıştırma ve bölge/dedupe kuralları (gerçek ağ çağrısı YOK; tarayıcı katmanı taklit edilir)."""

from packages.db.models import Region, Sector
from services.integrations.google_places import maps_provider as mp
from services.integrations.google_places.maps_provider import GoogleMapsProvider, query_terms
from services.research import google_maps
from services.research.browser import SourceBlocked
from services.research.models import MapsCandidate

CARD = {
    "name": "Lider İşitme Cihazları Merkezi",
    "href": "https://www.google.com/maps/place/Lider/data=!4m7!3m6!1s0x14ccb33601c0dfc3:0xcb385bfc6fc6e4b3!8m2!3d40.7569!4d30.3861",
    "text": "Lider İşitme Cihazları Merkezi | Lider İşitme Cihazları Merkezi | 5,0(65) | İşitme Cihazları Satıcısı · Adnan Menderes Cd. No:194 D:1 | Kapalı ⋅ Açılış zamanı: Cmt 09:00 · 0537 700 31 46 |   | \"10 yıldır bilginiz\"",
}


def test_parse_feed_card_reads_real_google_fields():
    c = google_maps.parse_feed_card(CARD)
    assert c.name == "Lider İşitme Cihazları Merkezi"
    assert (c.rating, c.review_count) == (5.0, 65)
    assert c.category == "İşitme Cihazları Satıcısı"
    assert c.address == "Adnan Menderes Cd. No:194 D:1"
    assert c.phone == "0537 700 31 46"
    assert (c.lat, c.lng) == (40.7569, 30.3861), "koordinat yalnızca !3d..!4d'den okunur"
    assert google_maps.place_id_from_url(c.url) == "0x14ccb33601c0dfc3:0xcb385bfc6fc6e4b3"


def test_feed_card_without_data_leaves_fields_none():
    c = google_maps.parse_feed_card({"name": "Yalnız İsim", "href": "https://www.google.com/maps/place/x/data=!1s0xa:0xb", "text": "Yalnız İsim"})
    assert c.rating is None and c.review_count is None and c.phone is None and c.address is None and c.lat is None


def test_query_terms_use_primary_sector_phrase_first(seeded_db):
    sector = seeded_db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    assert query_terms(sector)[0] == "işitme cihazı"
    assert len(query_terms(sector)) <= 2


def _region(db, name="Adapazarı"):
    return db.query(Region).filter_by(name=name, level="ilce").first()


def test_provider_maps_results_to_places_and_filters_outside_region(seeded_db, monkeypatch):
    region = _region(seeded_db)
    sector = seeded_db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    near = MapsCandidate(name="Yakın Merkez", url="https://g/maps/place/a/data=!1s0x1:0x2!3d1!4d1", lat=region.center_lat, lng=region.center_lng,
                         rating=4.5, review_count=10, category="İşitme Cihazları Satıcısı", address="X Cd.", phone="0264 111 22 33")
    far = MapsCandidate(name="Çok Uzak", url="https://g/maps/place/b/data=!1s0x3:0x4", lat=region.center_lat + 2.0, lng=region.center_lng)
    dup = MapsCandidate(name="Yakın Merkez (tekrar)", url=near.url, lat=near.lat, lng=near.lng)
    monkeypatch.setattr(google_maps, "search_places", lambda *a, **k: [near, far, dup])

    batches = []
    outcome = GoogleMapsProvider().search(region=region, sector=sector, target_count=10, on_batch=batches.append)

    assert outcome.provider_name == "google_maps" and outcome.is_demo_data is False
    assert [i.name for i in outcome.items] == ["Yakın Merkez"], "bölge dışı ve tekrar eden sonuçlar elenmeli"
    item = outcome.items[0]
    assert item.external_ref == "gmaps_0x1:0x2"
    assert item.rating == 4.5 and item.review_count == 10 and item.category_label == "İşitme Cihazları Satıcısı"
    assert item.phone == "0264 111 22 33" and item.maps_url == near.url
    assert item.website is None, "listede olmayan alan (web sitesi) uydurulmaz"
    assert len(batches) == 1


def test_provider_reports_google_block_in_turkish_without_retrying(seeded_db, monkeypatch):
    region = _region(seeded_db)
    sector = seeded_db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    calls = []

    def blocked(*a, **k):
        calls.append(1)
        raise SourceBlocked("google_maps", "CAPTCHA / sıra dışı trafik uyarısı")

    monkeypatch.setattr(google_maps, "search_places", blocked)
    try:
        GoogleMapsProvider().search(region=region, sector=sector, target_count=5)
        assert False, "engel görülünce açık bir hata fırlatılmalı"
    except RuntimeError as exc:
        assert "Google Haritalar otomatik erişimi engelledi" in str(exc) and "CAPTCHA" in str(exc)
        assert "Overpass" not in str(exc) and "OpenStreetMap" not in str(exc)
    assert len(calls) == 1, "engel aşılmaya çalışılmamalı (tekrar deneme yok)"
