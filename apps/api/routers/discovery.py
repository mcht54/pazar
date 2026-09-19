from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.deps import client_ip, current_user, require
from apps.api.schemas import DiscoveryJobCreate, DiscoveryJobOut
from packages.db.base import get_db
from packages.db.models import Business, DiscoveryJob, DiscoveryJobResult, Region, Sector, User
from services.auth.activity import log_activity
from services.worker.tasks.discovery import run_discovery_job_task

router = APIRouter(prefix="/api/discovery", tags=["keşif"])

MAX_TARGET_COUNT = 100


def _job_out(db: Session, job: DiscoveryJob) -> DiscoveryJobOut:
    out = DiscoveryJobOut.model_validate(job)
    counts = dict(
        db.query(Business.status, func.count(Business.id))
        .join(DiscoveryJobResult, DiscoveryJobResult.business_id == Business.id)
        .filter(DiscoveryJobResult.job_id == job.id)
        .group_by(Business.status)
        .all()
    )
    out.total_count = sum(counts.values())
    out.analyzed_count = counts.get("analyzed", 0)
    out.analyzing_count = counts.get("analyzing", 0)
    out.failed_analysis_count = counts.get("analysis_failed", 0)
    return out


@router.post("/jobs", response_model=DiscoveryJobOut)
def create_discovery_job(payload: DiscoveryJobCreate, request: Request, user: User = Depends(require("search")), db: Session = Depends(get_db)):
    region = db.get(Region, payload.region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="Bölge bulunamadı")
    sector = db.get(Sector, payload.sector_id)
    if sector is None or not sector.is_active:
        raise HTTPException(status_code=404, detail="Sektör bulunamadı")
    if payload.target_count <= 0 or payload.target_count > MAX_TARGET_COUNT:
        raise HTTPException(status_code=422, detail=f"İşletme sayısı 1-{MAX_TARGET_COUNT} arasında olmalı")

    job = DiscoveryJob(region_id=payload.region_id, sector_id=payload.sector_id, target_count=payload.target_count, user_id=user.id, requested_by=user.name)
    db.add(job)
    db.flush()
    log_activity(db, user, "search", detail=f"{region.name} · {sector.name} ({payload.target_count} işletme)", meta={"discovery_job_id": job.id, "region_id": region.id, "sector_id": sector.id}, ip=client_ip(request))
    db.commit()
    db.refresh(job)

    run_discovery_job_task.delay(job.id, payload.auto_analyze)
    return _job_out(db, job)


@router.get("/jobs/{job_id}", response_model=DiscoveryJobOut)
def get_discovery_job(job_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(DiscoveryJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Keşif görevi bulunamadı")
    return _job_out(db, job)
