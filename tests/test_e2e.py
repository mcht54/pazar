"""Uçtan uca: Şehir → ilçe → sektör → keşif → otomatik analiz → satış değerlendirmesi → öncelik sıralı liste.

Celery worker bu test ortamında koşmuyor; pipeline fonksiyonları (run_discovery_job / run_analysis_job) worker'ın
yapacağı işi senkron yapar — iş mantığı tamamen aynıdır (Celery sadece taşıma katmanıdır). Discovery/analiz için
DEMO (mock) sağlayıcı kullanılır; gerçek ağ çağrısı yoktur.
"""

import re

import pytest

from packages.db.base import SessionLocal
from packages.db.models import AnalysisJob, Business, BusinessMetric, Finding, SalesAssessment
from services.rule_engine.sales import LEVEL_ORDER
from services.worker.tasks import discovery as discovery_module
from services.worker.tasks.analysis import run_analysis_job
from services.worker.tasks.discovery import queue_analysis, run_discovery_job


class _SyncAnalysisTask:
    """run_analysis_job_task.delay yerine: kuyruğa alınan iş id'lerini toplar."""

    def __init__(self):
        self.queued: list[int] = []

    def delay(self, job_id: int):
        self.queued.append(job_id)


@pytest.fixture
def analysis_queue(monkeypatch):
    stub = _SyncAnalysisTask()
    monkeypatch.setattr(discovery_module, "run_analysis_job_task", stub)
    return stub


def _ids(client, region="Serdivan", sector="Restoran"):
    regions = {r["name"]: r["id"] for r in client.get("/api/regions").json()}
    sectors = {s["name"]: s["id"] for s in client.get("/api/sectors").json()}
    return regions[region], sectors[sector]


def _discover(client, analysis_queue, auto=True, target=10):
    region_id, sector_id = _ids(client)
    res = client.post("/api/discovery/jobs", json={"region_id": region_id, "sector_id": sector_id, "target_count": target, "auto_analyze": auto})
    assert res.status_code == 200
    job_id = res.json()["id"]
    db = SessionLocal()
    run_discovery_job(db, job_id, on_new_businesses=(lambda ids: queue_analysis(db, ids)) if auto else None)
    db.close()
    return region_id, sector_id, job_id


def _run_queued_analyses(analysis_queue):
    db = SessionLocal()
    for job_id in analysis_queue.queued:
        run_analysis_job(db, job_id)
    db.close()


def test_full_flow_discovery_auto_analysis_and_priority_list(client, analysis_queue):
    region_id, sector_id, job_id = _discover(client, analysis_queue)

    # 1) Keşif işletmeleri bulunca analiz OTOMATİK kuyruğa alındı (kullanıcı tek tek basmıyor)
    job = client.get(f"/api/discovery/jobs/{job_id}").json()
    assert job["total_count"] == 7
    assert job["analyzing_count"] == 7 and job["analyzed_count"] == 0
    assert len(analysis_queue.queued) == 7

    # 2) Analiz bitmeden liste: hepsi "bekliyor", satış seviyesi UYDURULMAZ
    before = client.get(f"/api/businesses?job_id={job_id}").json()
    assert all(b["sales_level"] is None for b in before)

    # 3) Worker analizleri yapar
    _run_queued_analyses(analysis_queue)
    job = client.get(f"/api/discovery/jobs/{job_id}").json()
    assert job["analyzed_count"] == 7 and job["analyzing_count"] == 0

    # 4) Liste satış önceliğine göre sıralı: Yüksek → Orta → Düşük → Belirsiz
    businesses = client.get(f"/api/businesses?job_id={job_id}").json()
    assert len(businesses) == 7
    orders = [LEVEL_ORDER[b["sales_level"]] for b in businesses]
    assert orders == sorted(orders, reverse=True), "işletmeler satış fırsatına göre sıralanmalı"
    for b in businesses:
        assert b["sales_level"] in LEVEL_ORDER
        assert b["sales_reason"] and b["why_call"] and b["sales_note"]
        assert b["is_demo_data"] is True and b["source_label"].startswith("DEMO")
        if b["sales_level"] in ("Yüksek", "Orta"):
            assert b["primary_service"], "Yüksek/Orta seviyede önerilen ilk hizmet olmalı"
            assert b["top_opportunity"] and b["gap_summary"]
        else:
            assert b["primary_service"] is None

    # 5) Seviye filtresi
    level = businesses[0]["sales_level"]
    filtered = client.get(f"/api/businesses?job_id={job_id}&level={level}").json()
    assert filtered and all(b["sales_level"] == level for b in filtered)


def test_without_auto_analyze_nothing_is_queued(client, analysis_queue):
    _, _, job_id = _discover(client, analysis_queue, auto=False)
    assert analysis_queue.queued == []
    assert client.get(f"/api/discovery/jobs/{job_id}").json()["analyzing_count"] == 0


def test_business_without_website_gets_corporate_site_recommendation(client, analysis_queue):
    region_id, sector_id, job_id = _discover(client, analysis_queue)
    _run_queued_analyses(analysis_queue)

    businesses = client.get(f"/api/businesses?job_id={job_id}").json()
    no_site = next(b for b in businesses if b["website"] is None)
    detail = client.get(f"/api/businesses/{no_site['id']}").json()
    a = detail["assessment"]
    assert a["primary_service"] == "Kurumsal Web Sitesi"
    presence = next(c for c in a["website"]["checks"] if c["key"] == "presence")
    assert presence["status"] == "problem" and presence["value"] == "Web sitesi bulunamadı"
    assert a["website"]["status_text"] == "Web sitesi bulunamadı."
    service_names = {s["service_name"] for s in detail["service_recommendations"]}
    assert "Kurumsal Web Sitesi" in service_names
    assert detail["service_recommendations"][0]["priority_rank"] == 1


def test_finding_evidence_chain_and_no_unsupported_findings(client, analysis_queue, db):
    _, _, job_id = _discover(client, analysis_queue)
    _run_queued_analyses(analysis_queue)

    findings = db.query(Finding).all()
    assert findings
    for f in findings:
        assert f.based_on_metric_ids, "her bulgu bir ölçüm kaydına dayanmalı"
        metrics = db.query(BusinessMetric).filter(BusinessMetric.id.in_(f.based_on_metric_ids)).all()
        assert len(metrics) == len(f.based_on_metric_ids)
        assert all(m.business_id == f.business_id and m.analysis_job_id == f.analysis_job_id for m in metrics)
        assert all(m.status == "known" for m in metrics), "'Doğrulanamadı' (not_available) ölçümden bulgu üretilemez"
        assert f.evidence and f.business_impact and f.severity in ("none", "low", "medium", "high")
        assert f.confidence in ("low", "medium", "high")


def test_visible_texts_are_turkish_and_never_show_internal_codes(client, analysis_queue):
    _, _, job_id = _discover(client, analysis_queue)
    _run_queued_analyses(analysis_queue)

    forbidden = ["not_available", "insufficient", "discovered", "analyzed", "Rating", "Website", "Google Business", "opportunity", "undefined", "None"]
    for b in client.get(f"/api/businesses?job_id={job_id}").json():
        texts = [b["sales_reason"], b["why_call"], b["sales_note"], b["top_opportunity"], b["gbp_summary"], b["web_summary"], b["source_label"], *b["gap_summary"]]
        detail = client.get(f"/api/businesses/{b['id']}").json()["assessment"]
        for area in ("website", "gbp"):
            for c in detail[area]["checks"]:
                texts += [c["label"], c["value"], c["detail"], c["why"]]
        for t in filter(None, texts):
            for word in forbidden:
                assert word not in t, f"kullanıcıya gösterilen metinde '{word}' var: {t!r}"


def test_missing_source_data_is_none_never_guessed(client, analysis_queue):
    """OSM sağlayıcısı puan/yorum vermez: alan None kalmalı (uydurulmamalı)."""
    from services.integrations.google_places.base import PlaceResult
    from services.worker.tasks.discovery import _upsert_business
    from packages.db.models import Region, Sector

    db = SessionLocal()
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    business, is_new = _upsert_business(
        db, region, sector, PlaceResult(external_ref="gmaps_42", success=True, name="Yalnız İsim İşitme"), source="google_maps"
    )
    db.commit()
    assert is_new
    b = client.get(f"/api/businesses/{business.id}").json()["business"]
    for field in ("address", "phone", "website", "email", "google_rating", "google_review_count", "photo_count", "opening_hours", "category_label", "maps_url", "last_review_at"):
        assert b[field] is None, f"{field} kaynakta yokken None olmalı"
    assert b["source_label"] == "Google Haritalar"
    db.close()


def test_business_without_research_gbp_section_is_all_unverified(client, analysis_queue, db):
    from packages.db.models import Region, Sector
    from services.integrations.google_places.base import PlaceResult
    from services.worker.tasks.discovery import _upsert_business

    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    business, _ = _upsert_business(
        db, region, sector,
        PlaceResult(external_ref="gmaps_77", success=True, name="Kaya İşitme", phone="0264 000 00 00", category_label="İşitme Cihazı Merkezi"),
        source="google_maps",
    )
    db.commit()

    job = AnalysisJob(business_id=business.id)
    db.add(job)
    db.commit()
    run_analysis_job(db, job.id)

    a = client.get(f"/api/businesses/{business.id}").json()["assessment"]
    assert a["gbp"]["available"] is False
    assert all(c["status"] == "unknown" for c in a["gbp"]["checks"])
    assert a["level"] == "Orta" and a["needs_verification"] is True
    assert a["primary_service"] == "Kurumsal Web Sitesi"
    assert any("Google Haritalar" in s for s in a["verification_steps"])
    summary = client.get(f"/api/businesses?region_id={region.id}&sector_id={sector.id}").json()[0]
    assert "doğrulanamadı" in summary["gbp_summary"].lower()


def test_failed_analysis_marks_business_and_can_be_requeued(client, analysis_queue, monkeypatch, db):
    _, _, job_id = _discover(client, analysis_queue, auto=False)
    business = db.query(Business).first()
    job = AnalysisJob(business_id=business.id)
    db.add(job)
    business.status = "analyzing"
    db.commit()

    from services.worker.tasks import analysis as analysis_module

    monkeypatch.setattr(analysis_module, "build_gbp_checks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("beklenmeyen")))
    with pytest.raises(RuntimeError):
        run_analysis_job(db, job.id)

    db.expire_all()
    assert db.get(Business, business.id).status == "analysis_failed", "başarısız analiz sonrası işletme sonsuza dek 'analiz ediliyor' kalmamalı"
    assert db.get(AnalysisJob, job.id).status == "failed"

    monkeypatch.undo()
    queued = queue_analysis(db, [business.id])
    assert len(queued) == 1, "başarısız analiz yeniden kuyruğa alınabilmeli"


def test_reanalysis_shows_only_latest_result(client, analysis_queue, db):
    _, _, job_id = _discover(client, analysis_queue)
    _run_queued_analyses(analysis_queue)
    business = db.query(Business).first()

    job = AnalysisJob(business_id=business.id)
    db.add(job)
    db.commit()
    run_analysis_job(db, job.id)

    detail = client.get(f"/api/businesses/{business.id}").json()
    finding_ids_by_job = {f["id"] for f in detail["findings"]}
    latest_findings = {f.id for f in db.query(Finding).filter_by(business_id=business.id, analysis_job_id=job.id)}
    assert finding_ids_by_job == latest_findings, "detayda sadece en son analizin bulguları görünmeli"
    assert db.query(SalesAssessment).filter_by(business_id=business.id).count() == 2
    assert all(re.match(r"^(Yüksek|Orta|Düşük|Belirsiz)$", detail["assessment"]["level"]) for _ in [0])
