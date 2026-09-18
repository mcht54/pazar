"""Test 4-10, 13(partial): Mock discovery, dedup, partial failure, job status, persistence."""

from packages.db.models import Business, DiscoveryJob, Region, Sector
from services.integrations.google_places.mock_provider import MockPlacesProvider
from services.worker.tasks.discovery import run_discovery_job


def _serdivan_restoran(db):
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="Restoran").one()
    return region, sector


def test_mock_provider_returns_results_without_network(seeded_db):
    region, sector = _serdivan_restoran(seeded_db)
    outcome = MockPlacesProvider().search(region=region, sector=sector, target_count=10)
    assert outcome.is_demo_data is True
    assert len(outcome.items) == 10


def test_mock_provider_deterministic_pagination_pattern(seeded_db):
    """target_count > tek 'sayfa' olsa bile (20 istek) tutarlı üretiyor mu."""
    region, sector = _serdivan_restoran(seeded_db)
    outcome = MockPlacesProvider().search(region=region, sector=sector, target_count=20)
    assert len(outcome.items) == 20
    successes = [i for i in outcome.items if i.success]
    assert len(successes) > 10  # birden fazla "sayfa" boyunca başarı üretebiliyor


def test_discovery_creates_target_businesses(seeded_db):
    region, sector = _serdivan_restoran(seeded_db)
    job = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=10)
    seeded_db.add(job)
    seeded_db.commit()
    seeded_db.refresh(job)

    result = run_discovery_job(seeded_db, job.id)

    assert result.found_new == 7
    assert result.found_existing == 1
    assert len(result.item_errors) == 2


def test_discovery_dedup_by_google_place_id(seeded_db):
    """Aynı region+sector için discovery iki kez çalıştırılınca duplicate Business oluşmamalı."""
    region, sector = _serdivan_restoran(seeded_db)

    job1 = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=10)
    seeded_db.add(job1)
    seeded_db.commit()
    seeded_db.refresh(job1)
    run_discovery_job(seeded_db, job1.id)

    count_after_first = seeded_db.query(Business).count()
    assert count_after_first == 7

    job2 = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=10)
    seeded_db.add(job2)
    seeded_db.commit()
    seeded_db.refresh(job2)
    result2 = run_discovery_job(seeded_db, job2.id)

    count_after_second = seeded_db.query(Business).count()
    assert count_after_second == count_after_first, "İkinci discovery çalıştırması yeni duplicate işletme oluşturmamalı"
    assert result2.found_existing == 8
    assert result2.found_new == 0

    place_ids = [b.google_place_id for b in seeded_db.query(Business).all()]
    assert len(place_ids) == len(set(place_ids)), "google_place_id tekil olmalı"


def test_discovery_partial_failure_status(seeded_db):
    region, sector = _serdivan_restoran(seeded_db)
    job = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=10)
    seeded_db.add(job)
    seeded_db.commit()
    seeded_db.refresh(job)

    result = run_discovery_job(seeded_db, job.id)

    assert result.status == "partial"
    assert len(result.item_errors) == 2
    for err in result.item_errors:
        assert err["reason"]  # uydurma değil, gerçek (simulated) hata nedeni kayıtlı
        assert err["external_ref"]


def test_discovery_job_status_lifecycle(seeded_db):
    region, sector = _serdivan_restoran(seeded_db)
    job = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=10)
    seeded_db.add(job)
    seeded_db.commit()
    seeded_db.refresh(job)
    assert job.status == "pending"

    result = run_discovery_job(seeded_db, job.id)
    assert result.status in ("completed", "partial", "failed")
    assert result.completed_at is not None


def test_discovery_reuses_existing_businesses_without_calling_provider(seeded_db, monkeypatch):
    """Performans/nezaket: yeterli işletme zaten DB'deyse dış servise tekrar istek atılmaz."""
    region, sector = _serdivan_restoran(seeded_db)

    job1 = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=5)
    seeded_db.add(job1)
    seeded_db.commit()
    seeded_db.refresh(job1)
    result1 = run_discovery_job(seeded_db, job1.id)
    assert result1.found_new == 4  # target=5 -> index4 başarısız, 4 başarılı, duplicate yok

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Yeterli işletme zaten varken provider tekrar çağrılmamalı")

    monkeypatch.setattr(
        "services.worker.tasks.discovery.get_places_provider",
        lambda db: type("Boom", (), {"search": _fail_if_called})(),
    )

    job2 = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=4)
    seeded_db.add(job2)
    seeded_db.commit()
    seeded_db.refresh(job2)
    result2 = run_discovery_job(seeded_db, job2.id)

    assert result2.status == "completed"
    assert result2.found_existing == 4
    assert result2.found_new == 0
    assert result2.item_errors == []


def test_discovery_persists_business_metrics(seeded_db):
    from packages.db.models import BusinessMetric

    region, sector = _serdivan_restoran(seeded_db)
    job = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=5)
    seeded_db.add(job)
    seeded_db.commit()
    seeded_db.refresh(job)
    run_discovery_job(seeded_db, job.id)

    business = seeded_db.query(Business).first()
    metrics = seeded_db.query(BusinessMetric).filter_by(business_id=business.id).all()
    metric_keys = {m.metric_key for m in metrics}
    assert {"google_rating", "google_review_count", "photo_count", "website_present", "phone_present"} <= metric_keys
    for m in metrics:
        assert m.status in ("known", "unknown", "unverified", "not_available")
        assert m.source == "mock_demo"
