from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.schemas import RegionOut, SectorOut
from packages.db.base import get_db
from packages.db.models import Region, Sector

router = APIRouter(prefix="/api", tags=["taxonomy"])


@router.get("/regions", response_model=list[RegionOut])
def list_regions(db: Session = Depends(get_db)):
    return db.query(Region).order_by(Region.level, Region.name).all()


@router.get("/sectors", response_model=list[SectorOut])
def list_sectors(db: Session = Depends(get_db)):
    return db.query(Sector).order_by(Sector.name).all()
