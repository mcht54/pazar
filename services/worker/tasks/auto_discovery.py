"""Otomatik keşif: MarkaKarnem'in "Günün fırsatı" / "Haftanın 1.si" havuzu her gün yeni gerçek işletmelerle büyüsün.

Neden: Pazar'a işletme yalnızca personel arama yaptığında giriyordu; havuz büyümeyince MarkaKarnem her gün/hafta aynı firmaları
buluyor ya da hiç bulamıyordu.

Kurallar:
- Yalnızca resmi Google Places API (Text Search) kullanılır. Tarayıcıyla Google Haritalar okuma (google_maps sağlayıcısı) otomatik
  çalıştırılmaz: Google'ın kullanım şartları otomatik erişime izin vermez, o yol yalnızca personelin kendi aramasıdır.
- Anahtar (GOOGLE_PLACES_API_KEY) yoksa hiçbir şey yapılmaz, nedeni açıkça döner. Günlük istek sınırı integrations_registry'den okunur.
- Sıra: hiç taranmamış ilçe + sektör ikilileri önce, sonra en uzun süredir taranmamış olan; eşitlikte rastgele (her gün farklı bölge/sektör).
- Kapsam: Pazar'ın asıl çalıştığı illerin (işletmelerin en az %20'si) ilçeleri ve aktif sektörler (rakip ajans sektörleri hariç).
  Tek tük araması yapılmış iller taranmaz: Haftanın 1.si aynı il + sektörde en az 3 işletme ister, dağınık tarama grup oluşturmaz.
- Bulunan işletmeler için Pazar'ın tarayıcılı ek araştırması otomatik başlatılmaz; MarkaKarnem kendi analizini yapar.
"""

import random
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.base import SessionLocal
from packages.db.models import Business, DiscoveryJob, Region, Sector
from services.worker.celery_app import celery_app

REQUESTED_BY = "otomatik keşif (MarkaKarnem)"
TARGET_COUNT = 60  # Text Search en fazla ~60 sonuç (3 sayfa) verir
MAX_PER_RUN = 3
MAIN_IL_SHARE = 0.2  # bir ilin kapsama girmesi için Pazar'daki işletmelerden aldığı en düşük pay
AGENCY_TERMS = ("ajans", "reklam", "web tasarım", "dijital pazarlama", "sosyal medya", "seo", "yazılım")


def available() -> str | None:
    """Otomatik keşif çalışamıyorsa nedeni; çalışabiliyorsa None."""
    if not settings.google_places_api_key:
        return "Pazar'da GOOGLE_PLACES_API_KEY tanımlı değil; otomatik keşif resmi Google Places API olmadan çalışmaz."
    return None


def _scope_regions(db: Session) -> list[Region]:
    """Pazar'ın asıl çalıştığı illerin ilçeleri (ilçesi tanımlı olmayan ilde ilin kendisi)."""
    counts = dict(db.query(Business.region_id, func.count(Business.id)).group_by(Business.region_id).all())
    if not counts:
        return []
    per_il: dict[int, int] = {}
    for r in db.query(Region).filter(Region.id.in_(counts)).all():
        il_id = r.parent_region_id if r.level == "ilce" else r.id
        per_il[il_id] = per_il.get(il_id, 0) + counts[r.id]
    total = sum(per_il.values())
    il_ids = {il_id for il_id, n in per_il.items() if n >= total * MAIN_IL_SHARE}
    ilceler = db.query(Region).filter(Region.level == "ilce", Region.parent_region_id.in_(il_ids)).all()
    with_ilce = {r.parent_region_id for r in ilceler}
    return ilceler + [r for r in db.query(Region).filter(Region.id.in_(il_ids - with_ilce)).all()]


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
    """Sıradaki ikililer için keşif işlerini oluşturur (çalıştırmaz)."""
    jobs = []
    for region, sector in next_combos(db, min(max(count, 1), MAX_PER_RUN)):
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
