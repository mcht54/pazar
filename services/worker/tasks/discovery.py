from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.db.base import SessionLocal
from packages.db.models import Business, BusinessMetric, DiscoveryJob, DiscoveryJobResult, Region, Sector
from services.integrations.google_places.base import PlaceResult, SearchOutcome
from services.integrations.google_places.factory import get_places_provider
from services.worker.celery_app import celery_app


@celery_app.task(name="worker.ping")
def ping() -> str:
    """Sprint 0 smoke-test task; confirms broker/worker wiring works."""
    return "pong"


def _record_metric(db: Session, business: Business, metric_key: str, value, source: str) -> None:
    status = "known" if value is not None else "not_available"
    db.add(
        BusinessMetric(
            business_id=business.id,
            analysis_job_id=None,
            metric_key=metric_key,
            value={"value": value},
            status=status,
            source=source,
        )
    )


def _upsert_business(db: Session, region: Region, sector: Sector, item: PlaceResult, source: str) -> tuple[Business, bool]:
    """Returns (business, is_new). Dedup key: google_place_id."""
    existing = db.query(Business).filter_by(google_place_id=item.external_ref).one_or_none()

    if existing is not None:
        # Duplicate/re-discovery: sadece gerçekten yeni veri varsa güncelle, boş tekrar sonuçlarla eski veriyi ezme.
        if item.name:
            existing.name = item.name
        if item.address:
            existing.address = item.address
        if item.rating is not None:
            existing.google_rating = item.rating
        if item.review_count is not None:
            existing.google_review_count = item.review_count
        if item.photo_count is not None:
            existing.photo_count = item.photo_count
        if item.website:
            existing.website = item.website
        if item.phone:
            existing.phone = item.phone
        db.flush()
        return existing, False

    business = Business(
        name=item.name or "(isimsiz işletme)",
        sector_id=sector.id,
        region_id=region.id,
        address=item.address,
        lat=item.lat,
        lng=item.lng,
        phone=item.phone,
        website=item.website,
        google_place_id=item.external_ref,
        google_rating=item.rating,
        google_review_count=item.review_count,
        photo_count=item.photo_count,
        discovery_source=source,
        status="discovered",
    )
    db.add(business)
    db.flush()  # id almak için

    _record_metric(db, business, "google_rating", item.rating, source)
    _record_metric(db, business, "google_review_count", item.review_count, source)
    _record_metric(db, business, "photo_count", item.photo_count, source)
    _record_metric(db, business, "website_present", bool(item.website), source)
    _record_metric(db, business, "phone_present", bool(item.phone), source)

    return business, True


def run_discovery_job(db: Session, discovery_job_id: int) -> DiscoveryJob:
    job = db.get(DiscoveryJob, discovery_job_id)
    if job is None:
        raise ValueError(f"DiscoveryJob {discovery_job_id} bulunamadı")

    job.status = "running"
    db.commit()

    region = db.get(Region, job.region_id)
    sector = db.get(Sector, job.sector_id)

    provider = get_places_provider(db)

    try:
        outcome: SearchOutcome = provider.search(
            region_name=region.name, sector_name=sector.name, target_count=job.target_count
        )
    except Exception as exc:  # provider tamamen ulaşılamaz durumda (kota, ağ, config hatası)
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return job

    found_new = 0
    found_existing = 0
    item_errors: list[dict] = []

    for item in outcome.items:
        if not item.success:
            item_errors.append({"external_ref": item.external_ref, "reason": item.error_reason})
            continue

        business, is_new = _upsert_business(db, region, sector, item, source=outcome.provider_name)
        existing_link = (
            db.query(DiscoveryJobResult).filter_by(job_id=job.id, business_id=business.id).one_or_none()
        )
        if existing_link is None:
            db.add(DiscoveryJobResult(job_id=job.id, business_id=business.id))

        if is_new:
            found_new += 1
        else:
            found_existing += 1

    job.found_new = found_new
    job.found_existing = found_existing
    job.item_errors = item_errors

    total_attempted = len(outcome.items)
    total_failed = len(item_errors)
    total_success = total_attempted - total_failed

    if total_attempted == 0:
        job.status = "completed"
    elif total_success == 0:
        job.status = "failed"
    elif total_failed > 0:
        job.status = "partial"
    else:
        job.status = "completed"

    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    return job


@celery_app.task(name="worker.run_discovery_job")
def run_discovery_job_task(discovery_job_id: int) -> str:
    db = SessionLocal()
    try:
        job = run_discovery_job(db, discovery_job_id)
        return job.status
    finally:
        db.close()
