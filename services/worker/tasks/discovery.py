from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from packages.db.base import SessionLocal
from packages.localization import normalize_host
from services.research.dedupe import same_business
from packages.db.models import AnalysisJob, Business, BusinessMetric, DiscoveryJob, DiscoveryJobResult, Region, Sector
from services.integrations.google_places.base import PlaceResult, SearchOutcome
from services.integrations.google_places.factory import get_places_provider
from services.worker.celery_app import celery_app
from services.worker.tasks.analysis import run_analysis_job_task


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


def _source_profile(item: PlaceResult) -> dict:
    """Kaynaktan gelen ek profil verisi — sadece kaynağın gerçekten verdiği alanlar."""
    profile = dict(item.profile or {})
    profile["categories"] = item.categories
    if item.source_url:
        profile["source_url"] = item.source_url
    if item.photo_count is not None:
        profile["photos_capped"] = item.photos_capped
    if item.reviews_sampled is not None:
        profile["reviews_sampled"] = item.reviews_sampled
    return profile


def _upsert_business(db: Session, region: Region, sector: Sector, item: PlaceResult, source: str) -> tuple[Business, bool]:
    """Returns (business, is_new). Dedup key: google_place_id."""
    existing = db.query(Business).filter_by(google_place_id=item.external_ref).one_or_none()
    if existing is None and item.lat is not None and item.lng is not None:
        # Farklı bir Google kaydı olarak gelse de AYNI işletme olabilir (ad + konum + telefon): yeni kayıt açılmaz, mevcut işletme kullanılır.
        box = 0.002  # ≈ 220 m
        nearby = db.query(Business).filter(Business.lat.between(item.lat - box, item.lat + box), Business.lng.between(item.lng - box, item.lng + box)).all()
        candidate = {"name": item.name, "phone": item.phone, "lat": item.lat, "lng": item.lng}
        existing = next((b for b in nearby if same_business(candidate, {"name": b.name, "phone": b.phone, "lat": b.lat, "lng": b.lng})[0]), None)
    if existing is None and item.website:
        # Aynı işletme farklı kaynak kaydı olarak gelebilir (ör. OSM'de iki kayıt, www'li/www'suz adres):
        # aynı bölge+sektörde aynı web sitesi alan adına sahip kayıt varsa yeni işletme açılmaz.
        host = normalize_host(item.website)
        candidates = db.query(Business).filter(
            Business.region_id == region.id, Business.sector_id == sector.id, Business.website.isnot(None)
        ).all()
        existing = next((c for c in candidates if normalize_host(c.website) == host), None)
    now = datetime.now(timezone.utc)

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
        if item.email:
            existing.email = item.email
        if item.opening_hours:
            existing.opening_hours = item.opening_hours
        if item.category_label:
            existing.category_label = item.category_label
        if item.maps_url:
            existing.maps_url = item.maps_url
        if item.last_review_at:
            existing.last_review_at = item.last_review_at
        existing.source_profile = _source_profile(item)
        existing.source_checked_at = now
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
        email=item.email,
        google_place_id=item.external_ref,
        google_rating=item.rating,
        google_review_count=item.review_count,
        photo_count=item.photo_count,
        opening_hours=item.opening_hours,
        discovery_source=source,
        category_label=item.category_label,
        maps_url=item.maps_url,
        last_review_at=item.last_review_at,
        source_checked_at=now,
        source_profile=_source_profile(item),
        status="discovered",
    )
    db.add(business)
    db.flush()  # id almak için

    _record_metric(db, business, "google_rating", item.rating, source)
    _record_metric(db, business, "google_review_count", item.review_count, source)
    _record_metric(db, business, "photo_count", item.photo_count, source)
    _record_metric(db, business, "website_present", bool(item.website), source)
    _record_metric(db, business, "phone_present", bool(item.phone), source)
    _record_metric(db, business, "email_present", bool(item.email), source)

    return business, True


def _link_job_result(db: Session, job: DiscoveryJob, business: Business) -> None:
    existing_link = db.query(DiscoveryJobResult).filter_by(job_id=job.id, business_id=business.id).one_or_none()
    if existing_link is None:
        db.add(DiscoveryJobResult(job_id=job.id, business_id=business.id))


def queue_analysis(db: Session, business_ids: list[int], user_id: int | None = None) -> list[int]:
    """Henüz analiz edilmemiş işletmeler için analiz görevi oluşturup kuyruğa alır.

    Döndürür: kuyruğa alınan AnalysisJob id'leri. Zaten analiz edilmiş/edilmekte olan
    işletmeler atlanır (gereksiz tekrar tarama yapılmaz).
    """
    job_ids: list[int] = []
    for business in db.query(Business).filter(Business.id.in_(business_ids), Business.status.in_(("discovered", "analysis_failed"))).all():
        analysis_job = AnalysisJob(business_id=business.id, user_id=user_id)  # analizi başlatan kullanıcı (aramayı yapan)
        db.add(analysis_job)
        business.status = "analyzing"
        db.flush()
        job_ids.append(analysis_job.id)
    db.commit()
    for analysis_job_id in job_ids:
        run_analysis_job_task.delay(analysis_job_id)
    return job_ids


def run_discovery_job(
    db: Session,
    discovery_job_id: int,
    on_new_businesses: Callable[[list[int]], None] | None = None,
) -> DiscoveryJob:
    """on_new_businesses: her veri grubu DB'ye yazılıp commit edildikçe, o gruptaki işletme
    id'leriyle çağrılır (worker burada analizi kuyruğa alır; testler vermez)."""
    job = db.get(DiscoveryJob, discovery_job_id)
    if job is None:
        raise ValueError(f"DiscoveryJob {discovery_job_id} bulunamadı")

    job.status = "running"
    db.commit()

    region = db.get(Region, job.region_id)
    sector = db.get(Sector, job.sector_id)

    # Performans/nezaket: aynı bölge+sektör için zaten yeterli işletme varsa dış
    # servise tekrar istek atmadan mevcut kayıtları kullan (gereksiz API çağrısı yapma).
    already_known = (
        db.query(Business)
        .filter(Business.region_id == region.id, Business.sector_id == sector.id)
        .order_by(Business.id.asc())
        .limit(job.target_count)
        .all()
    )
    if len(already_known) >= job.target_count:
        for business in already_known:
            _link_job_result(db, job, business)
        if on_new_businesses:
            on_new_businesses([b.id for b in already_known])
        job.found_new = 0
        job.found_existing = len(already_known)
        job.item_errors = []
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return job

    provider = get_places_provider(db)

    counters = {"found_new": 0, "found_existing": 0}
    item_errors: list[dict] = []

    def _process_batch(batch: list[PlaceResult]) -> None:
        """Sağlayıcıdan bir veri grubu (sayfa/genişletme denemesi) geldikçe hemen DB'ye
        yazar ve commit eder — kullanıcı arama bitmeden sonuçları görebilsin diye."""
        batch_ids: list[int] = []
        for item in batch:
            if not item.success:
                item_errors.append({"external_ref": item.external_ref, "reason": item.error_reason})
                continue
            business, is_new = _upsert_business(db, region, sector, item, source=provider.name)
            _link_job_result(db, job, business)
            batch_ids.append(business.id)
            counters["found_new" if is_new else "found_existing"] += 1
        job.found_new = counters["found_new"]
        job.found_existing = counters["found_existing"]
        job.item_errors = list(item_errors)
        db.commit()
        if on_new_businesses and batch_ids:
            on_new_businesses(batch_ids)

    try:
        outcome: SearchOutcome = provider.search(
            region=region, sector=sector, target_count=job.target_count, on_batch=_process_batch
        )
    except Exception as exc:  # provider tamamen ulaşılamaz durumda (kota, ağ, config hatası)
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return job

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
def run_discovery_job_task(discovery_job_id: int, auto_analyze: bool = True) -> str:
    """auto_analyze=True: bulunan her işletme için Google profili + web sitesi analizi
    otomatik başlatılır (kullanıcı tek tek 'Analiz Et'e basmak zorunda kalmaz)."""
    db = SessionLocal()
    try:
        discovery_row = db.get(DiscoveryJob, discovery_job_id)
        starter_id = discovery_row.user_id if discovery_row else None
        callback = (lambda ids: queue_analysis(db, ids, starter_id)) if auto_analyze else None
        job = run_discovery_job(db, discovery_job_id, on_new_businesses=callback)
        return job.status
    finally:
        db.close()
