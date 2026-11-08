"""Otomatik keşif: MarkaKarnem'in "Günün fırsatı" / "Haftanın 1.si" havuzu her gün yeni gerçek işletmelerle büyüsün.

Neden: Pazar'a işletme yalnızca personel arama yaptığında giriyordu; havuz büyümeyince MarkaKarnem her gün/hafta aynı firmaları
buluyor ya da hiç bulamıyordu.

Kurallar:
- Yalnızca resmi Google Places API (Text Search) kullanılır. Tarayıcıyla Google Haritalar okuma (google_maps sağlayıcısı) otomatik
  çalıştırılmaz: Google'ın kullanım şartları otomatik erişime izin vermez, o yol yalnızca personelin kendi aramasıdır.
- Anahtar (GOOGLE_PLACES_API_KEY) yoksa hiçbir şey yapılmaz, nedeni açıkça döner.
- Kota: günde en fazla KARNE_DISCOVER_DAILY_JOBS arama, ayda en fazla KARNE_DISCOVER_MONTHLY_REQUESTS Places isteği (api_usage_ledger);
  her arama en fazla 2 sayfa (2 istek). Sınırdaysa arama başlatılmaz, nedeni döner (Google'ın ücretsiz aylık kotası aşılmasın).
- Sıra: hiç taranmamış ilçe + sektör ikilileri önce, sonra en uzun süredir taranmamış olan; eşitlikte rastgele (her gün farklı bölge/sektör).
- Kapsam: yalnızca KARNE_DISCOVER_IL (varsayılan Sakarya) ilçeleri ve aktif sektörler (rakip ajans sektörleri hariç).
- Bulunan işletmeler için Pazar'ın tarayıcılı ek araştırması otomatik başlatılmaz; MarkaKarnem kendi analizini yapar.
"""

import random
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.base import SessionLocal
from packages.db.models import ApiUsageLedger, DiscoveryJob, Region, Sector
from services.worker.celery_app import celery_app

REQUESTED_BY = "otomatik keşif (MarkaKarnem)"
TARGET_COUNT = 40  # en fazla 2 sayfa (sayfa başına 20 sonuç) → arama başına en fazla 2 Places isteği
REQUESTS_PER_JOB = 2
MAX_PER_RUN = 3
AGENCY_TERMS = ("ajans", "reklam", "web tasarım", "dijital pazarlama", "sosyal medya", "seo", "yazılım")


def _istanbul_today() -> date:
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


def month_requests(db: Session) -> int:
    """Bu ay yapılan Places isteği (api_usage_ledger; günlük kova "YYYY-MM-DD")."""
    prefix = date.today().strftime("%Y-%m")
    return (db.query(func.count(ApiUsageLedger.id))
            .filter(ApiUsageLedger.integration_name == "google_places", ApiUsageLedger.quota_period.like(f"{prefix}-%")).scalar() or 0)


def jobs_today(db: Session) -> int:
    start = datetime.combine(_istanbul_today(), datetime.min.time(), ZoneInfo("Europe/Istanbul"))
    return db.query(func.count(DiscoveryJob.id)).filter(DiscoveryJob.requested_by == REQUESTED_BY, DiscoveryJob.created_at >= start).scalar() or 0


def allowance(db: Session) -> tuple[int, str | None]:
    """(bugün başlatılabilecek arama sayısı, sıfırsa nedeni)."""
    if not settings.google_places_api_key:
        return 0, "Pazar'da GOOGLE_PLACES_API_KEY tanımlı değil; otomatik keşif resmi Google Places API olmadan çalışmaz."
    by_month = (settings.karne_discover_monthly_requests - month_requests(db)) // REQUESTS_PER_JOB
    if by_month <= 0:
        return 0, f"Bu ayın Google Places sınırı doldu ({settings.karne_discover_monthly_requests} istek); otomatik keşif ay başında devam eder."
    by_day = settings.karne_discover_daily_jobs - jobs_today(db)
    if by_day <= 0:
        return 0, f"Bugünkü otomatik keşif hakkı kullanıldı (günde {settings.karne_discover_daily_jobs} arama); yarın devam eder."
    return min(by_month, by_day), None


def _scope_regions(db: Session) -> list[Region]:
    """KARNE_DISCOVER_IL ilinin ilçeleri (ilçesi tanımlı değilse ilin kendisi)."""
    want = settings.karne_discover_il.strip().casefold()
    il = next((r for r in db.query(Region).filter(Region.level == "il").all() if r.name.casefold() == want), None)
    if il is None:
        return []
    return db.query(Region).filter(Region.level == "ilce", Region.parent_region_id == il.id).all() or [il]


def _scope_sectors(db: Session) -> list[Sector]:
    return [s for s in db.query(Sector).filter(Sector.is_active.is_(True)).all() if not any(t in s.name.casefold() for t in AGENCY_TERMS)]


def next_combos(db: Session, count: int = 1, rng: random.Random | None = None) -> list[tuple[Region, Sector]]:
    """Taranacak sıradaki ilçe + sektör ikilileri: hiç taranmamışlar önce, sonra en eski tarananlar; aynı çalıştırmada her sektör en fazla bir kez."""
    rng = rng or random.Random()
    last = {(r, s): t for r, s, t in db.query(DiscoveryJob.region_id, DiscoveryJob.sector_id, func.max(DiscoveryJob.created_at))
            .group_by(DiscoveryJob.region_id, DiscoveryJob.sector_id).all()}
    floor = datetime.min.replace(tzinfo=timezone.utc)
    combos = [(region, sector) for region in _scope_regions(db) for sector in _scope_sectors(db)]
    rng.shuffle(combos)
    combos.sort(key=lambda c: last.get((c[0].id, c[1].id)) or floor)  # kararlı sıralama: eşitlikte karışık sıra korunur
    picked, sectors = [], set()
    for region, sector in combos:
        if sector.id in sectors:
            continue
        picked.append((region, sector))
        sectors.add(sector.id)
        if len(picked) >= count:
            break
    return picked


def plan(db: Session, count: int = 1) -> list[DiscoveryJob]:
    """Sıradaki ikililer için keşif işlerini oluşturur (çalıştırmaz); günlük/aylık hakkı aşmaz."""
    allowed, _why = allowance(db)
    jobs = []
    for region, sector in next_combos(db, min(max(count, 1), MAX_PER_RUN, allowed)) if allowed else []:
        job = DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=TARGET_COUNT, status="pending", requested_by=REQUESTED_BY)
        db.add(job)
        jobs.append(job)
    db.commit()
    return jobs


def run(db: Session, job_ids: list[int]) -> list[str]:
    from services.integrations.google_places.google_provider import GooglePlacesProvider
    from services.worker.tasks.discovery import run_discovery_job

    statuses = []
    for job_id in job_ids:
        statuses.append(run_discovery_job(db, job_id, provider=GooglePlacesProvider(db)).status)
    return statuses


@celery_app.task(name="worker.auto_discovery")
def auto_discovery_task(job_ids: list[int]) -> list[str]:
    db = SessionLocal()
    try:
        return run(db, job_ids)
    finally:
        db.close()
