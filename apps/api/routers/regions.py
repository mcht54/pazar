from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.deps import current_user
from apps.api.schemas import RegionOut, SectorOut
from packages.db.base import get_db
from packages.db.models import Region, Sector, User

router = APIRouter(prefix="/api", tags=["sınıflandırma"])


@router.get("/regions", response_model=list[RegionOut])
def list_regions(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(Region).order_by(Region.level, Region.name).all()


@router.get("/sectors", response_model=list[SectorOut])
def list_sectors(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(Sector).filter(Sector.is_active.is_(True)).order_by(Sector.group_name, Sector.name).all()
