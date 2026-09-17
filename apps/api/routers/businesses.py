from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas import (
    AnalysisJobOut,
    AnalyzeBulkRequest,
    BusinessDetailOut,
    BusinessMetricOut,
    BusinessOut,
    CompetitorMetricRow,
    FindingOut,
    OpportunityScoreOut,
    ServiceRecommendationOut,
)
from packages.db.base import get_db
from packages.db.models import (
    AnalysisJob,
    Business,
    BusinessMetric,
    CompetitorSnapshot,
    Finding,
    OpportunityScore,
    ServiceCatalog,
    ServiceRecommendation,
)
from services.rule_engine.competitor import COMPETITOR_METRIC_KEYS
from services.worker.tasks.analysis import run_analysis_job_task

router = APIRouter(prefix="/api/businesses", tags=["businesses"])


def _to_business_out(business: Business) -> BusinessOut:
    return BusinessOut.from_orm_business(business)


@router.get("", response_model=list[BusinessOut])
def list_businesses(
    region_id: int | None = None,
    sector_id: int | None = None,
    crm_stage: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Business)
    if region_id is not None:
        query = query.filter(Business.region_id == region_id)
    if sector_id is not None:
        query = query.filter(Business.sector_id == sector_id)
    if crm_stage is not None:
        query = query.filter(Business.crm_stage == crm_stage)
    businesses = query.order_by(Business.created_at.desc()).all()
    return [_to_business_out(b) for b in businesses]


def _build_competitor_rows(db: Session, business: Business, latest_job_id: int | None) -> list[CompetitorMetricRow]:
    if latest_job_id is None:
        return []
    snapshots = db.query(CompetitorSnapshot).filter_by(business_id=business.id, analysis_job_id=latest_job_id).all()
    if not snapshots:
        return []

    self_metrics = {
        m.metric_key: m
        for m in db.query(BusinessMetric)
        .filter(BusinessMetric.business_id == business.id, BusinessMetric.metric_key.in_(COMPETITOR_METRIC_KEYS))
        .order_by(BusinessMetric.id.asc())
        .all()
    }

    competitor_names = {
        row.id: row.name
        for row in db.query(Business).filter(Business.id.in_({s.competitor_business_id for s in snapshots})).all()
    }

    rows: dict[str, CompetitorMetricRow] = {}
    for metric_key in COMPETITOR_METRIC_KEYS:
        self_metric = self_metrics.get(metric_key)
        rows[metric_key] = CompetitorMetricRow(
            metric_key=metric_key,
            business_value=self_metric.value if self_metric else None,
            business_status=self_metric.status if self_metric else "not_available",
            competitors=[],
        )

    for snapshot in snapshots:
        rows[snapshot.metric_key].competitors.append(
            {
                "competitor_id": snapshot.competitor_business_id,
                "competitor_name": competitor_names.get(snapshot.competitor_business_id, "?"),
                "value": snapshot.value,
                "status": snapshot.status,
            }
        )

    return list(rows.values())


@router.get("/{business_id}", response_model=BusinessDetailOut)
def get_business_detail(business_id: int, db: Session = Depends(get_db)):
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="İşletme bulunamadı")

    latest_job = (
        db.query(AnalysisJob).filter_by(business_id=business_id).order_by(AnalysisJob.id.desc()).first()
    )
    latest_job_id = latest_job.id if latest_job else None

    # Metrikler: discovery'den gelenler (analysis_job_id IS NULL) + en son analizin ürettikleri.
    metrics = (
        db.query(BusinessMetric)
        .filter(
            BusinessMetric.business_id == business_id,
            (BusinessMetric.analysis_job_id.is_(None)) | (BusinessMetric.analysis_job_id == latest_job_id),
        )
        .order_by(BusinessMetric.id.desc())
        .all()
    )
    # Findings/scores/recommendations: sadece EN SON analiz — eski analiz koşuları tekrar tekrar birikmesin.
    findings = (
        db.query(Finding)
        .filter(Finding.business_id == business_id, Finding.analysis_job_id == latest_job_id)
        .order_by(Finding.id.desc())
        .all()
        if latest_job_id
        else []
    )
    scores = (
        db.query(OpportunityScore)
        .filter(OpportunityScore.business_id == business_id, OpportunityScore.analysis_job_id == latest_job_id)
        .order_by(OpportunityScore.id.desc())
        .all()
        if latest_job_id
        else []
    )

    recs = (
        db.query(ServiceRecommendation, ServiceCatalog.service_name)
        .join(ServiceCatalog, ServiceCatalog.id == ServiceRecommendation.service_id)
        .filter(ServiceRecommendation.business_id == business_id, ServiceRecommendation.analysis_job_id == latest_job_id)
        .order_by(ServiceRecommendation.priority_rank.asc())
        .all()
        if latest_job_id
        else []
    )
    recommendation_out = [
        ServiceRecommendationOut(
            service_id=rec.service_id,
            service_name=name,
            priority_rank=rec.priority_rank,
            matched_rule=rec.matched_rule,
            ai_justification=rec.ai_justification,
        )
        for rec, name in recs
    ]

    return BusinessDetailOut(
        business=_to_business_out(business),
        metrics=[BusinessMetricOut.model_validate(m) for m in metrics],
        findings=[FindingOut.model_validate(f) for f in findings],
        opportunity_scores=[OpportunityScoreOut.model_validate(s) for s in scores],
        service_recommendations=recommendation_out,
        competitors=_build_competitor_rows(db, business, latest_job_id),
        latest_analysis_job=AnalysisJobOut.model_validate(latest_job) if latest_job else None,
    )


@router.post("/{business_id}/analyze", response_model=AnalysisJobOut)
def analyze_business(business_id: int, db: Session = Depends(get_db)):
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="İşletme bulunamadı")

    job = AnalysisJob(business_id=business_id)
    db.add(job)
    business.status = "analyzing"
    db.commit()
    db.refresh(job)

    run_analysis_job_task.delay(job.id)
    return job


@router.post("/analyze-bulk", response_model=list[AnalysisJobOut])
def analyze_bulk(payload: AnalyzeBulkRequest, db: Session = Depends(get_db)):
    if not payload.business_ids and not payload.top_n:
        raise HTTPException(status_code=422, detail="business_ids veya top_n belirtilmeli — tüm işletmeler otomatik analiz edilmez")

    if payload.business_ids:
        businesses = db.query(Business).filter(Business.id.in_(payload.business_ids)).all()
    else:
        if payload.top_n <= 0 or payload.top_n > 100:
            raise HTTPException(status_code=422, detail="top_n 1-100 arasında olmalı")
        # Henüz analiz edilmemiş, en yeni keşfedilen top_n işletme (maliyet kontrolü: kullanıcı açıkça seçmeli)
        businesses = (
            db.query(Business)
            .filter(Business.status == "discovered")
            .order_by(Business.created_at.asc())
            .limit(payload.top_n)
            .all()
        )

    jobs = []
    for business in businesses:
        job = AnalysisJob(business_id=business.id)
        db.add(job)
        business.status = "analyzing"
        db.flush()
        jobs.append(job)
    db.commit()

    for job in jobs:
        db.refresh(job)
        run_analysis_job_task.delay(job.id)

    return jobs
