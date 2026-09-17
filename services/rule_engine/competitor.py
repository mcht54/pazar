"""Temel rakip karşılaştırması — ek API çağrısı yapmadan, zaten Discovery ile
toplanmış aynı bölge/sektördeki işletmelerin verisiyle yan yana karşılaştırma.

Karşılaştırılamayan metrikler tahmin edilmez; status=not_available olarak kaydedilir.
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.db.models import Business, BusinessMetric, CompetitorSnapshot

COMPETITOR_METRIC_KEYS = ["google_rating", "google_review_count", "website_present", "photo_count"]
MAX_COMPETITORS = 3


def _latest_metric_value(db: Session, business_id: int, metric_key: str):
    row = (
        db.query(BusinessMetric)
        .filter_by(business_id=business_id, metric_key=metric_key)
        .order_by(BusinessMetric.id.desc())
        .first()
    )
    if row is None:
        return None, "not_available"
    value = (row.value or {}).get("value")
    return value, row.status


def build_competitor_snapshots(db: Session, business: Business, analysis_job_id: int | None) -> list[CompetitorSnapshot]:
    competitors = (
        db.query(Business)
        .filter(
            Business.region_id == business.region_id,
            Business.sector_id == business.sector_id,
            Business.id != business.id,
        )
        .order_by(func.coalesce(Business.google_review_count, 0).desc())
        .limit(MAX_COMPETITORS)
        .all()
    )

    snapshots: list[CompetitorSnapshot] = []
    for competitor in competitors:
        for metric_key in COMPETITOR_METRIC_KEYS:
            value, status = _latest_metric_value(db, competitor.id, metric_key)
            snapshot = CompetitorSnapshot(
                business_id=business.id,
                analysis_job_id=analysis_job_id,
                competitor_business_id=competitor.id,
                metric_key=metric_key,
                value={"value": value} if value is not None else None,
                status=status,
                source="places",
                collected_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)
            snapshots.append(snapshot)

    db.flush()
    return snapshots
