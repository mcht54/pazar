from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.deps import current_user
from apps.api.schemas import AnalysisJobOut
from packages.db.base import get_db
from packages.db.models import AnalysisJob, User

router = APIRouter(prefix="/api/analysis-jobs", tags=["analiz"])


@router.get("/{job_id}", response_model=AnalysisJobOut)
def get_analysis_job(job_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analiz görevi bulunamadı")
    return job
