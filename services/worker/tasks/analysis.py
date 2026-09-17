from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.db.base import SessionLocal
from packages.db.models import AnalysisJob, Business, BusinessMetric
from services.ai_orchestration.pipelines.evidence_extraction import extract_findings
from services.ai_orchestration.pipelines.interpret import run_ai_interpretation
from services.integrations.website_crawler.factory import get_website_analyzer
from services.rule_engine.competitor import build_competitor_snapshots
from services.rule_engine.matcher import build_service_recommendations
from services.rule_engine.scoring import compute_opportunity_scores, compute_overall_score
from services.worker.celery_app import celery_app

CRAWL_METRIC_KEYS = [
    "https_enabled",
    "title_present",
    "meta_description_present",
    "h1_present",
    "schema_markup_present",
    "whatsapp_link_present",
    "phone_link_present",
    "reservation_link_present",
    "instagram_link_present",
    "facebook_link_present",
]


def _record(db: Session, business: Business, analysis_job_id: int, metric_key: str, value, status: str, source: str) -> None:
    db.add(
        BusinessMetric(
            business_id=business.id,
            analysis_job_id=analysis_job_id,
            metric_key=metric_key,
            value={"value": value} if value is not None else None,
            status=status,
            source=source,
        )
    )


def _run_website_stage(db: Session, business: Business, job: AnalysisJob) -> str:
    """Döndürür: 'success' (website yok ya da başarıyla tarandı) | 'failed' (siteye erişilemedi)."""
    if not business.website:
        return "success"

    analyzer = get_website_analyzer(business_is_demo=business.discovery_source == "mock_demo")
    signals = analyzer.analyze(business.website)

    if not signals.success:
        _record(db, business, job.id, "website_reachable", False, "not_available", "website_crawl")
        for key in CRAWL_METRIC_KEYS:
            _record(db, business, job.id, key, None, "not_available", "website_crawl")
        # error_reason'ı evidence extraction'ın okuyabilmesi için website_reachable metriğine gömelim
        db.flush()
        last = (
            db.query(BusinessMetric)
            .filter_by(business_id=business.id, analysis_job_id=job.id, metric_key="website_reachable")
            .order_by(BusinessMetric.id.desc())
            .first()
        )
        last.value = {"value": False, "error_reason": signals.error_reason}
        return "failed"

    _record(db, business, job.id, "website_reachable", True, "known", "website_crawl")
    for key in CRAWL_METRIC_KEYS:
        value = getattr(signals, key)
        _record(db, business, job.id, key, value, "known" if value is not None else "not_available", "website_crawl")
    _record(db, business, job.id, "page_load_ms", signals.page_load_ms, "known" if signals.page_load_ms else "not_available", "website_crawl")
    return "success"


def run_analysis_job(db: Session, analysis_job_id: int) -> AnalysisJob:
    job = db.get(AnalysisJob, analysis_job_id)
    if job is None:
        raise ValueError(f"AnalysisJob {analysis_job_id} bulunamadı")

    business = db.get(Business, job.business_id)
    stages: dict[str, str] = {}

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    # 1) places: discovery sırasında zaten toplandı, burada sadece mevcut kabul edilir.
    stages["places"] = "success"

    # 2) website (+ social, aynı crawl'dan türetilir)
    try:
        stages["website"] = _run_website_stage(db, business, job)
        stages["social"] = stages["website"]
    except Exception as exc:  # beklenmeyen crawler hatası — job'u komple düşürme
        stages["website"] = "failed"
        stages["social"] = "failed"
        db.add(
            BusinessMetric(
                business_id=business.id, analysis_job_id=job.id, metric_key="website_reachable",
                value={"value": False, "error_reason": str(exc)}, status="not_available", source="website_crawl",
            )
        )

    db.commit()

    # 3) Evidence Extraction (deterministik)
    try:
        findings = extract_findings(db, business, job.id)
        stages["evidence_extraction"] = "success"
    except Exception:
        stages["evidence_extraction"] = "failed"
        job.status = "failed"
        job.stages_status = stages
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise

    # 4) Rule Engine -> Service Recommendations
    build_service_recommendations(db, business.id, job.id, findings)
    stages["rule_engine"] = "success"

    # 5) Opportunity Scoring
    scores = compute_opportunity_scores(db, business, job.id, findings)
    stages["scoring"] = "success"
    overall_score, priority = compute_overall_score(scores, findings)
    business.opportunity_score_total = overall_score
    business.sales_priority = priority

    # 6) Competitor snapshot (aynı bölge/sektör, ek API çağrısı yok)
    competitors = build_competitor_snapshots(db, business, job.id)
    stages["competitor"] = "success" if competitors else "skipped"

    # 7) AI yorumlama (opsiyonel — ANTHROPIC_API_KEY yoksa atlanır)
    try:
        stages["ai_interpretation"] = run_ai_interpretation(db, business.id, job.id)
    except NotImplementedError:
        stages["ai_interpretation"] = "skipped"

    business.status = "analyzed"
    business.last_analysis_at = datetime.now(timezone.utc)

    failed_data_stages = [s for s in ("website", "social") if stages.get(s) == "failed"]
    job.status = "partial" if failed_data_stages else "completed"
    job.stages_status = stages
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    return job


@celery_app.task(name="worker.run_analysis_job")
def run_analysis_job_task(analysis_job_id: int) -> str:
    db = SessionLocal()
    try:
        job = run_analysis_job(db, analysis_job_id)
        return job.status
    finally:
        db.close()
