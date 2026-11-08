"""Otomatik keşif: anahtarsız çalışmaz, sıradaki ikili hiç taranmamış olandan seçilir, her gün farklı ilçe/sektör gelir,
yalnızca resmi Places API sağlayıcısı kullanılır."""

import random
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.api.main import app
from packages.config import settings
from packages.db.models import Business, DiscoveryJob, Region, Sector
from services.integrations.google_places.base import PlaceResult, SearchOutcome
from services.worker.tasks import auto_discovery

HEADERS = {"X-Feed-Token": "t" * 40, "X-Requested-With": "mch-app"}


def _anchor(db):
    """Pazar'ın Sakarya'da çalıştığını gösteren tek işletme (kapsam bu ilin ilçeleri olur)."""
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    db.add(Business(name="Çapa", sector_id=sector.id, region_id=region.id, google_place_id="p_capa", discovery_source="google_places", status="analyzed"))
    db.commit()
    return region


def test_discover_requires_token_and_places_key(seeded_db, monkeypatch):
    c = TestClient(app)
    monkeypatch.setattr(settings, "karne_feed_token", "t" * 40)
    assert c.post("/api/feed/karne-discover", headers={**HEADERS, "X-Feed-Token": "yanlis"}).status_code == 401
    monkeypatch.setattr(settings, "google_places_api_key", "")
    r = c.post("/api/feed/karne-discover", headers=HEADERS)
    assert r.status_code == 503 and "GOOGLE_PLACES_API_KEY" in r.json()["detail"]
    assert seeded_db.query(DiscoveryJob).count() == 0


def test_discover_queues_jobs_for_distinct_sectors_in_scope(seeded_db, monkeypatch):
    db = seeded_db
    anchor = _anchor(db)
    monkeypatch.setattr(settings, "karne_feed_token", "t" * 40)
    monkeypatch.setattr(settings, "google_places_api_key", "anahtar")
    sent = []
    monkeypatch.setattr(auto_discovery.auto_discovery_task, "delay", lambda ids: sent.append(ids))
    r = TestClient(app).post("/api/feed/karne-discover?count=3", headers=HEADERS)
    assert r.status_code == 202, r.text
    queued = r.json()["queued"]
    assert len(queued) == 3 and len({q["sector"] for q in queued}) == 3, "aynı çalıştırmada her sektör bir kez"
    assert all(q["il"] == anchor.parent.name for q in queued), "yalnızca Pazar'ın çalıştığı ilin ilçeleri"
    assert not any("ajans" in q["sector"].casefold() or "reklam" in q["sector"].casefold() for q in queued)
    assert sent == [[q["job_id"] for q in queued]]
    jobs = db.query(DiscoveryJob).all()
    assert all(j.requested_by == auto_discovery.REQUESTED_BY and j.status == "pending" for j in jobs)


def test_next_combos_prefers_never_scanned_then_oldest(seeded_db):
    db = seeded_db
    _anchor(db)
    scanned = {(r.id, s.id) for r in auto_discovery._scope_regions(db) for s in auto_discovery._scope_sectors(db)}
    # Biri hariç tüm sektörler taranmış olsun: sıradaki ikili taranmamış sektörden gelmeli
    first = auto_discovery.next_combos(db, count=1, rng=random.Random(1))[0]
    old = datetime.now(timezone.utc) - timedelta(days=30)
    for region_id, sector_id in scanned:
        if sector_id != first[1].id:
            db.add(DiscoveryJob(region_id=region_id, sector_id=sector_id, target_count=60, status="completed", created_at=old))
    db.commit()
    for seed in range(5):
        r, s = auto_discovery.next_combos(db, count=1, rng=random.Random(seed))[0]
        assert s.id == first[1].id, "hiç taranmamış ikili önce gelir"


def test_consecutive_days_get_different_combos(seeded_db):
    db = seeded_db
    _anchor(db)
    seen = set()
    for _day in range(5):
        jobs = auto_discovery.plan(db, 2)
        for j in jobs:
            assert (j.region_id, j.sector_id) not in seen, "aynı ilçe + sektör kısa sürede tekrar taranmaz"
            seen.add((j.region_id, j.sector_id))


def test_run_uses_official_places_provider(seeded_db, monkeypatch):
    db = seeded_db
    _anchor(db)
    job = auto_discovery.plan(db, 1)[0]
    used = []

    class FakePlaces:
        name = "google_places"

        def __init__(self, _db):
            used.append(True)

        def search(self, *, region, sector, target_count, on_batch=None):
            item = PlaceResult(external_ref="google_yeni1", success=True, name="Yeni İşletme", lat=region.center_lat, lng=region.center_lng,
                               phone="0532 000 00 01", rating=4.7, review_count=120)
            if on_batch:
                on_batch([item])
            return SearchOutcome(provider_name=self.name, is_demo_data=False, items=[item])

    import services.integrations.google_places.google_provider as gp

    monkeypatch.setattr(gp, "GooglePlacesProvider", FakePlaces)
    monkeypatch.setattr("services.worker.tasks.discovery.get_places_provider",
                        lambda _db: (_ for _ in ()).throw(AssertionError("ayardaki tarayıcılı sağlayıcı kullanılmamalı")))
    assert auto_discovery.run(db, [job.id]) == ["completed"]
    assert used and db.query(Business).filter_by(google_place_id="google_yeni1").one().google_review_count == 120


def test_scope_is_limited_to_main_provinces(seeded_db):
    db = seeded_db
    anchor = _anchor(db)
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    for n in range(4):  # Sakarya'da 5 işletme
        db.add(Business(name=f"S{n}", sector_id=sector.id, region_id=anchor.id, google_place_id=f"p_s{n}", discovery_source="google_places", status="analyzed"))
    other = db.query(Region).filter(Region.level == "il", Region.id != anchor.parent_region_id).first()
    db.add(Business(name="Uzak", sector_id=sector.id, region_id=other.id, google_place_id="p_uzak", discovery_source="google_places", status="analyzed"))
    db.commit()
    il_ids = {r.parent_region_id if r.level == "ilce" else r.id for r in auto_discovery._scope_regions(db)}
    assert il_ids == {anchor.parent_region_id}, "tek işletmeli il (%17) taranmaz"
