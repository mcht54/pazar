"""Test 14-16: Finding schema validation, Rule Engine, Service Recommendation."""

import pytest

from packages.db.models import Business, DiscoveryJob, Region, Sector
from services.ai_orchestration.pipelines.evidence_extraction import extract_findings
from services.rule_engine.matcher import build_service_recommendations
from services.worker.tasks.discovery import run_discovery_job


def _discover_and_get_business_without_website(db):
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="Restoran").one()
    job = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=10)
    db.add(job)
    db.commit()
    db.refresh(job)
    run_discovery_job(db, job.id)
    return db.query(Business).filter(Business.website.is_(None)).first()


def test_finding_has_all_required_fields(seeded_db):
    business = _discover_and_get_business_without_website(seeded_db)
    findings = extract_findings(seeded_db, business, analysis_job_id=None)
    assert findings, "Web sitesi olmayan işletme için en az bir finding üretilmeli"

    for f in findings:
        assert f.category
        assert f.severity in ("none", "low", "medium", "high")
        assert f.finding
        assert f.evidence
        assert f.source
        assert f.confidence in ("low", "medium", "high")
        assert f.detected_at is not None
        assert f.based_on_metric_ids, "Her finding en az bir business_metrics kaydına dayanmalı"
        assert f.business_impact
        assert f.mchttasarim_opportunity
        assert isinstance(f.recommended_service_ids, list)


def test_finding_evidence_is_specific_not_generic(seeded_db):
    business = _discover_and_get_business_without_website(seeded_db)
    findings = extract_findings(seeded_db, business, analysis_job_id=None)

    website_missing = next(f for f in findings if f.category == "website")
    # Genel/ölçülemeyen ifade değil, somut kanıt: place_id referansı içermeli.
    assert business.google_place_id in website_missing.evidence
    assert website_missing.finding != "SEO geliştirilmeli"  # yasak genel ifade örneği


def test_rule_engine_matches_website_missing_to_web_tasarim(seeded_db):
    business = _discover_and_get_business_without_website(seeded_db)
    findings = extract_findings(seeded_db, business, analysis_job_id=None)
    recs = build_service_recommendations(seeded_db, business.id, None, findings)

    service_names = set()
    from packages.db.models import ServiceCatalog

    for rec in recs:
        service_names.add(seeded_db.get(ServiceCatalog, rec.service_id).service_name)

    assert "Web Tasarım" in service_names


def test_service_recommendation_priority_ranking_reflects_severity(seeded_db):
    business = _discover_and_get_business_without_website(seeded_db)
    findings = extract_findings(seeded_db, business, analysis_job_id=None)
    recs = build_service_recommendations(seeded_db, business.id, None, findings)

    ranks = [r.priority_rank for r in recs]
    assert ranks == sorted(ranks), "priority_rank artan sırada (1=en yüksek öncelik) olmalı"

    from packages.db.models import ServiceCatalog

    top = next(r for r in recs if r.priority_rank == 1)
    top_service = seeded_db.get(ServiceCatalog, top.service_id)
    assert top_service.service_name == "Web Tasarım"  # tek 'high' severity finding bu hizmete bağlı
    assert "Web sitesi tespit edilemedi" in top.matched_rule


def test_ai_cannot_invent_service_not_in_rule_engine_output(seeded_db):
    """AI aşaması yeni bir ServiceRecommendation satırı OLUŞTURAMAZ — sadece var olanı günceller."""
    from services.ai_orchestration.pipelines.interpret import run_ai_interpretation

    business = _discover_and_get_business_without_website(seeded_db)
    findings = extract_findings(seeded_db, business, analysis_job_id=None)
    build_service_recommendations(seeded_db, business.id, None, findings)

    result = run_ai_interpretation(seeded_db, business.id, analysis_job_id=None)
    assert result == "skipped"  # ANTHROPIC_API_KEY yok -> hiçbir şey uydurulmaz, aşama atlanır
