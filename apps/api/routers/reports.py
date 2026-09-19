from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.deps import require
from apps.api.routers.businesses import _build_business_out, _latest_assessments, _load_extras, _presentation_maps
from packages.db.base import get_db
from packages.db.models import Business, User
from services.reporting.analysis_stats import PERIODS, analysis_report, analyzed_business_ids

router = APIRouter(prefix="/api/reports", tags=["raporlar"])


@router.get("/analysis")
def analysis_counters(_: User = Depends(require("dashboard")), db: Session = Depends(get_db)):
    """'📊 ANALİZ RAPORU': bugün / bu hafta / bu ay / toplam TAMAMLANAN analiz işlemi sayısı (Europe/Istanbul), gerçek analiz kayıtlarından."""
    return analysis_report(db)


@router.get("/analysis/businesses")
def analyzed_businesses(period: str = "today", user: User = Depends(require("view_business")), db: Session = Depends(get_db)):
    """Seçilen dönemde analizi tamamlanan firmalar (tekil firma; aynı firma birden çok analiz edildiyse `runs` işlem sayısını gösterir)."""
    if period not in PERIODS:
        raise HTTPException(status_code=422, detail=f"Geçersiz dönem. Geçerli: {', '.join(PERIODS)}")
    ids, analyses = analyzed_business_ids(db, period)
    order = {bid: i for i, bid in enumerate(ids)}
    businesses = sorted(db.query(Business).filter(Business.id.in_(ids)).all(), key=lambda b: order[b.id]) if ids else []
    assessments = _latest_assessments(db, ids)
    sector_names, region_labels, service_names = _presentation_maps(db)
    extras = _load_extras(db, businesses, user)
    return {
        "period": period,
        "label": PERIODS[period],
        "analyses": analyses,
        "businesses_count": len(businesses),
        "items": [
            _build_business_out(b, sector_names=sector_names, region_labels=region_labels, service_names=service_names, assessment=assessments.get(b.id), extras=extras).model_dump(mode="json")
            for b in businesses
        ],
    }
