from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas import AnalysisJobOut
from packages.db.base import get_db
from packages.db.models import AnalysisJob

router = APIRouter(prefix="/api/analysis-jobs", tags=["analysis"])


@router.get("/{job_id}", response_model=AnalysisJobOut)
def get_analysis_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job bulunamadı")
    return job
