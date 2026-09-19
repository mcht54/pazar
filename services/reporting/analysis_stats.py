"""Analiz sayaçları (bugün / bu hafta / bu ay / toplam): GERÇEK analiz geçmişinden (analysis_jobs) hesaplanır.

KURALLAR
- Analiz sayısı = başarıyla TAMAMLANMIŞ analiz işlemi (`status = 'completed'`). Kısmen tamamlanan (`partial`), başarısız (`failed`), sürmekte olan ve
  yalnızca keşif/arama yapan işlemler sayılmaz.
- Firma sayısı = aynı aralıkta en az bir başarılı analizi olan BENZERSİZ firma (COUNT DISTINCT business_id). Aynı firma 5 kez analiz edildiyse
  analiz = 5, firma = 1.
- Bakım amaçlı (personel işi olmayan) toplu yeniden hesaplamalar (`trigger = 'maintenance'`) sayılmaz.
- Aralıklar Europe/Istanbul'a göre YARI AÇIK [başlangıç, bitiş): bugün = bugün 00:00 → yarın 00:00; hafta = Pazartesi 00:00 → gelecek Pazartesi 00:00;
  ay = ayın 1'i 00:00 → sonraki ayın 1'i 00:00; toplam = tüm kayıtlar. Hesap sunucuda yapılır; tarayıcı saatine güvenilmez.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.db.models import AnalysisJob

TZ = ZoneInfo("Europe/Istanbul")
COUNTED_STATUSES = ("completed",)  # yalnızca başarıyla tamamlananlar (partial/failed/running/pending sayılmaz)
PERIODS = {"today": "Bugün", "week": "Bu Hafta", "month": "Bu Ay", "total": "Toplam"}


def period_bounds(now: datetime) -> dict[str, tuple[datetime | None, datetime | None]]:
    """Dönem aralıkları (tz-aware, Europe/Istanbul): {"today": (başlangıç, bitiş), ...}; `total` için (None, None)."""
    local = now.astimezone(TZ)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())  # Pazartesi 00:00
    month = day.replace(day=1)
    next_month = (month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1))
    return {
        "today": (day, day + timedelta(days=1)),
        "week": (week, week + timedelta(days=7)),
        "month": (month, next_month),
        "total": (None, None),
    }


def period_starts(now: datetime) -> dict[str, datetime | None]:
    """Geriye dönük uyumluluk: yalnızca başlangıçlar."""
    return {k: v[0] for k, v in period_bounds(now).items()}


def _base(db: Session, start: datetime | None, end: datetime | None):
    query = db.query(AnalysisJob).filter(
        AnalysisJob.status.in_(COUNTED_STATUSES), AnalysisJob.trigger != "maintenance", AnalysisJob.completed_at.isnot(None)
    )
    if start is not None:
        query = query.filter(AnalysisJob.completed_at >= start)
    if end is not None:
        query = query.filter(AnalysisJob.completed_at < end)
    return query


def analysis_report(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    report: dict = {"timezone": "Europe/Istanbul", "updated_at": now.astimezone(TZ).isoformat()}
    for key, (start, end) in period_bounds(now).items():
        query = _base(db, start, end)
        analyses = query.with_entities(func.count(AnalysisJob.id)).scalar() or 0
        businesses = query.with_entities(func.count(func.distinct(AnalysisJob.business_id))).scalar() or 0
        report[key] = {"analyses": analyses, "businesses": businesses, "since": start.isoformat() if start else None, "until": end.isoformat() if end else None}
    first = _base(db, None, None).with_entities(func.min(AnalysisJob.completed_at)).scalar()
    report["first_analysis_at"] = first.astimezone(TZ).isoformat() if first else None
    return report


def analyzed_business_ids(db: Session, period: str, now: datetime | None = None) -> tuple[list[int], int]:
    """Dönemde başarıyla analiz edilen firmalar (tekil), en son analizi en yeni olan başta. Döndürür: (firma kimlikleri, analiz sayısı)."""
    now = now or datetime.now(timezone.utc)
    start, end = period_bounds(now)[period]
    query = _base(db, start, end)
    analyses = query.with_entities(func.count(AnalysisJob.id)).scalar() or 0
    rows = (
        query.with_entities(AnalysisJob.business_id, func.max(AnalysisJob.completed_at).label("last"))
        .group_by(AnalysisJob.business_id)
        .order_by(func.max(AnalysisJob.completed_at).desc())
        .all()
    )
    return [r.business_id for r in rows], analyses
