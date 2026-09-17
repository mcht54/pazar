"""Uçtan uca test: Serdivan → Restoran → 10 işletme → Discovery → Business list →
İşletme detay → Analiz → Finding → Service recommendation.

Celery worker bu test ortamında koşmuyor; API job'u oluşturur, pipeline fonksiyonları
(run_discovery_job / run_analysis_job) worker'ın yapacağı işi senkron olarak yapar —
iş mantığının kendisi tamamen aynıdır (Celery sadece taşıma katmanıdır).
"""

from packages.db.base import SessionLocal
from packages.db.models import AnalysisJob
from services.worker.tasks.analysis import run_analysis_job
from services.worker.tasks.discovery import run_discovery_job


def test_full_discovery_to_service_recommendation_flow(client):
    # 1) Bölge/sektör seç
    regions = {r["name"]: r["id"] for r in client.get("/api/regions").json()}
    sectors = {s["name"]: s["id"] for s in client.get("/api/sectors").json()}
    serdivan_id = regions["Serdivan"]
    restoran_id = sectors["Restoran"]

    # 2) Discovery job oluştur (API) ve çalıştır
    job_res = client.post(
        "/api/discovery/jobs", json={"region_id": serdivan_id, "sector_id": restoran_id, "target_count": 10}
    )
    assert job_res.status_code == 200
    job_id = job_res.json()["id"]

    db = SessionLocal()
    discovery_result = run_discovery_job(db, job_id)
    assert discovery_result.status == "partial"
    assert discovery_result.found_new == 7
    assert len(discovery_result.item_errors) == 2
    db.close()

    # 3) Business list
    list_res = client.get(f"/api/businesses?region_id={serdivan_id}&sector_id={restoran_id}")
    assert list_res.status_code == 200
    businesses = list_res.json()
    assert len(businesses) == 7
    assert all(b["is_demo_data"] for b in businesses)

    target_business = next(b for b in businesses if b["website"] is None)

    # 4) İşletme detay (analizden önce — findings boş olmalı)
    detail_before = client.get(f"/api/businesses/{target_business['id']}").json()
    assert detail_before["findings"] == []
    assert detail_before["latest_analysis_job"] is None

    # 5) Analiz Et
    analyze_res = client.post(f"/api/businesses/{target_business['id']}/analyze")
    assert analyze_res.status_code == 200
    analysis_job_id = analyze_res.json()["id"]

    db = SessionLocal()
    analysis_result = run_analysis_job(db, analysis_job_id)
    assert analysis_result.status in ("completed", "partial")
    db.close()

    # 6) Finding üretildi mi (kanıta dayalı)
    detail_after = client.get(f"/api/businesses/{target_business['id']}").json()
    assert len(detail_after["findings"]) >= 1
    website_finding = next(f for f in detail_after["findings"] if f["category"] == "website")
    assert website_finding["source"] == "places"
    assert website_finding["confidence"] == "high"
    assert website_finding["evidence"]
    assert website_finding["business_impact"]
    assert website_finding["mchttasarim_opportunity"]

    # 7) Service recommendation üretildi mi ve Web Tasarım'ı içeriyor mu
    service_names = {s["service_name"] for s in detail_after["service_recommendations"]}
    assert "Web Tasarım" in service_names

    # 8) Opportunity score boyutları eksiksiz (7 boyut) — insufficient_data dahil, uydurma skor yok
    dimensions = {s["dimension"] for s in detail_after["opportunity_scores"]}
    assert dimensions == {"web", "seo", "google_visibility", "social", "ads", "design", "print"}
    for score in detail_after["opportunity_scores"]:
        if score["status"] == "insufficient_data":
            assert score["score"] is None
        else:
            assert 0 <= score["score"] <= 100

    # 9) CRM/durum güncellendi
    assert detail_after["business"]["status"] == "analyzed"
    assert detail_after["business"]["opportunity_score_total"] is not None
