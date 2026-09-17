from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas import DiscoveryJobCreate, DiscoveryJobOut
from packages.db.base import get_db
from packages.db.models import DiscoveryJob, Region, Sector
from services.worker.tasks.discovery import run_discovery_job_task

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/jobs", response_model=DiscoveryJobOut)
def create_discovery_job(payload: DiscoveryJobCreate, db: Session = Depends(get_db)):
    if db.get(Region, payload.region_id) is None:
        raise HTTPException(status_code=404, detail="Bölge bulunamadı")
    if db.get(Sector, payload.sector_id) is None:
        raise HTTPException(status_code=404, detail="Sektör bulunamadı")
    if payload.target_count <= 0 or payload.target_count > 200:
        raise HTTPException(status_code=422, detail="İşletme sayısı 1-200 arasında olmalı")

    job = DiscoveryJob(region_id=payload.region_id, sector_id=payload.sector_id, target_count=payload.target_count)
    db.add(job)
    db.commit()
    db.refresh(job)

    run_discovery_job_task.delay(job.id)
    return job


@router.get("/jobs/{job_id}", response_model=DiscoveryJobOut)
def get_discovery_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(DiscoveryJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Discovery job bulunamadı")
    return job
