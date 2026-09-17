"""Test 1-3, 11-12, 17: Region/Sector selection, Discovery job creation, Business list/detail, API error handling."""

import time


def test_list_regions(client):
    res = client.get("/api/regions")
    assert res.status_code == 200
    names = {r["name"] for r in res.json()}
    assert {"Sakarya", "Serdivan", "Adapazarı", "Erenler", "Kocaeli"} <= names


def test_list_sectors(client):
    res = client.get("/api/sectors")
    assert res.status_code == 200
    names = {s["name"] for s in res.json()}
    assert "Restoran" in names


def _region_sector_ids(client):
    regions = {r["name"]: r["id"] for r in client.get("/api/regions").json()}
    sectors = {s["name"]: s["id"] for s in client.get("/api/sectors").json()}
    return regions["Serdivan"], sectors["Restoran"]


def test_create_discovery_job(client):
    region_id, sector_id = _region_sector_ids(client)
    res = client.post("/api/discovery/jobs", json={"region_id": region_id, "sector_id": sector_id, "target_count": 10})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["target_count"] == 10


def _run_discovery_synchronously(client, region_id, sector_id, target_count=10):
    """API üzerinden job oluşturur; Celery worker koşmadığı test ortamında pipeline'ı
    doğrudan çağırarak (aynı iş mantığı) job'u işler."""
    from packages.db.base import SessionLocal
    from services.worker.tasks.discovery import run_discovery_job

    res = client.post(
        "/api/discovery/jobs", json={"region_id": region_id, "sector_id": sector_id, "target_count": target_count}
    )
    job_id = res.json()["id"]

    db = SessionLocal()
    run_discovery_job(db, job_id)
    db.close()
    return job_id


def test_business_list_endpoint(client):
    region_id, sector_id = _region_sector_ids(client)
    _run_discovery_synchronously(client, region_id, sector_id)

    res = client.get(f"/api/businesses?region_id={region_id}&sector_id={sector_id}")
    assert res.status_code == 200
    businesses = res.json()
    assert len(businesses) == 7
    first = businesses[0]
    for field in ("name", "address", "phone", "website", "google_rating", "google_review_count", "is_demo_data", "status"):
        assert field in first
    assert all(b["is_demo_data"] for b in businesses)


def test_business_detail_endpoint(client):
    region_id, sector_id = _region_sector_ids(client)
    _run_discovery_synchronously(client, region_id, sector_id)
    business_id = client.get(f"/api/businesses?region_id={region_id}").json()[0]["id"]

    res = client.get(f"/api/businesses/{business_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["business"]["id"] == business_id
    assert "metrics" in body and "findings" in body and "opportunity_scores" in body
    assert "service_recommendations" in body and "competitors" in body


def test_analyze_endpoint_runs_full_pipeline(client):
    from packages.db.base import SessionLocal
    from services.worker.tasks.analysis import run_analysis_job
    from packages.db.models import AnalysisJob

    region_id, sector_id = _region_sector_ids(client)
    _run_discovery_synchronously(client, region_id, sector_id)
    business_id = client.get(f"/api/businesses?region_id={region_id}").json()[0]["id"]

    db = SessionLocal()
    job = AnalysisJob(business_id=business_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    run_analysis_job(db, job.id)
    db.close()

    detail = client.get(f"/api/businesses/{business_id}").json()
    assert detail["latest_analysis_job"]["status"] in ("completed", "partial")
    assert len(detail["findings"]) > 0
    assert len(detail["opportunity_scores"]) == 7  # 7 boyut, insufficient_data olanlar dahil


def test_404_for_unknown_business(client):
    res = client.get("/api/businesses/999999")
    assert res.status_code == 404
    assert "detail" in res.json()


def test_404_for_unknown_region_on_discovery(client):
    res = client.post("/api/discovery/jobs", json={"region_id": 999999, "sector_id": 1, "target_count": 5})
    assert res.status_code == 404


def test_422_for_invalid_target_count(client):
    region_id, sector_id = _region_sector_ids(client)
    res = client.post("/api/discovery/jobs", json={"region_id": region_id, "sector_id": sector_id, "target_count": 500})
    assert res.status_code == 422


def test_analyze_bulk_requires_explicit_selection(client):
    res = client.post("/api/businesses/analyze-bulk", json={})
    assert res.status_code == 422, "Tüm işletmeler kullanıcı onayı olmadan otomatik analiz edilmemeli (maliyet kontrolü)"
