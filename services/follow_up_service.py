"""Takipler (follow_ups): işletme + kullanıcı + tarih + saat + not + durum (Bekliyor / Tamamlandı / İptal).

- Bir işletmede birden çok takip olabilir. `businesses.next_follow_up_at/follow_up_note` yalnızca EN YAKIN bekleyen takibin önbelleğidir
  (CRM listesi/filtresi/indeksler için); gerçek kaynak bu tablodur ve her değişiklikte senkronlanır.
- Gün, Europe/Istanbul takvim gününe göredir. Saat girilmediyse yalnızca gün tutulur (has_time=False). Saati geçmiş ama günü bugün olan takip "bugün"dür
  (`time_passed=True` ile işaretlenir); günü geçmiş olan "gecikmiş"tir.
- Kapanan (Kazanıldı/Kaybedildi) firmalarda bekleyen takipler İPTAL edilir (silinmez).
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.db.models import Business, FollowUp, User

TZ = ZoneInfo("Europe/Istanbul")
PENDING, DONE, CANCELLED = "Bekliyor", "Tamamlandı", "İptal"
STATUSES = (PENDING, DONE, CANCELLED)
RANGES = ("today", "overdue", "tomorrow", "week", "upcoming", "all")


def _has_time(raw, when: datetime) -> bool:
    if isinstance(raw, str) and len(raw.strip()) == 10:
        return False
    local = when.astimezone(TZ)
    return not (local.hour == 0 and local.minute == 0)


def date_state(due_at: datetime, now: datetime | None = None) -> str:
    """overdue | today | upcoming (Europe/Istanbul takvim günü)."""
    today = (now or datetime.now(timezone.utc)).astimezone(TZ).date()
    due = due_at.astimezone(TZ).date()
    return "overdue" if due < today else "today" if due == today else "upcoming"


def time_passed(fu: FollowUp, now: datetime | None = None) -> bool:
    return bool(fu.has_time and fu.status == PENDING and fu.due_at <= (now or datetime.now(timezone.utc)))


def week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Bu hafta: bugünün başlangıcı → gelecek Pazartesi 00:00 (Europe/Istanbul)."""
    local = (now or datetime.now(timezone.utc)).astimezone(TZ)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day, day + timedelta(days=7 - day.weekday())


def range_bounds(name: str, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    """[başlangıç, bitiş) — due_at için. overdue: bugünden önce; today; tomorrow; week: bugün→gelecek Pazartesi; upcoming: yarından sonra."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "overdue":
        return None, day
    if name == "today":
        return day, day + timedelta(days=1)
    if name == "tomorrow":
        return day + timedelta(days=1), day + timedelta(days=2)
    if name == "week":
        return week_bounds(now)
    if name == "upcoming":
        return day + timedelta(days=1), None
    return None, None


def pending_for(db: Session, business_id: int) -> list[FollowUp]:
    return db.query(FollowUp).filter(FollowUp.business_id == business_id, FollowUp.status == PENDING).order_by(FollowUp.due_at, FollowUp.id).all()


def sync_cache(db: Session, business: Business) -> None:
    """En yakın bekleyen takibi business.next_follow_up_at / follow_up_note önbelleğine yazar (yoksa temizler)."""
    db.flush()
    nxt = db.query(FollowUp).filter(FollowUp.business_id == business.id, FollowUp.status == PENDING).order_by(FollowUp.due_at, FollowUp.id).first()
    business.next_follow_up_at = nxt.due_at if nxt else None
    business.follow_up_note = nxt.note if nxt else None


def create(db: Session, business: Business, due_raw, note: str | None, *, owner_id: int | None, actor: User | None) -> FollowUp:
    from services import crm_service as crm

    when = crm.parse_follow_up(due_raw)
    if when is None:
        raise crm.CrmError(422, "Takip tarihi zorunlu.")
    if business.crm_stage in ("Kazanıldı", "Kaybedildi"):
        raise crm.CrmError(422, "Kapanmış (Kazanıldı/Kaybedildi) kayıtlar için takip girilemez.")
    fu = FollowUp(business_id=business.id, user_id=owner_id if owner_id is not None else (business.crm_owner_id or (actor.id if actor else None)),
                  created_by=actor.id if actor else None, due_at=when, has_time=_has_time(due_raw, when), note=((note or "").strip()[:1000]) or None, status=PENDING)
    db.add(fu)
    sync_cache(db, business)
    return fu


def set_primary(db: Session, business: Business, due_raw, *, note=None, note_provided: bool = False, due_provided: bool = False, actor: User | None = None) -> None:
    """CRM formundaki tek 'sonraki takip' alanı: en yakın bekleyen takibi günceller (yoksa oluşturur); tarih boşsa bekleyenleri İPTAL eder."""
    from services import crm_service as crm

    pending = pending_for(db, business.id)
    if due_provided:
        when = crm.parse_follow_up(due_raw)
        if when is None:
            for fu in pending:
                fu.status, fu.result, fu.completed_at = CANCELLED, "Takip kaldırıldı", datetime.now(timezone.utc)
        elif pending:
            pending[0].due_at, pending[0].has_time = when, _has_time(due_raw, when)
            if note_provided:
                pending[0].note = ((note or "").strip()[:1000]) or None
        else:
            create(db, business, due_raw, note if note_provided else None, owner_id=None, actor=actor)
    elif note_provided and pending:
        pending[0].note = ((note or "").strip()[:1000]) or None
    sync_cache(db, business)


def cancel_all_pending(db: Session, business: Business, reason: str) -> int:
    n = 0
    for fu in pending_for(db, business.id):
        fu.status, fu.result, fu.completed_at = CANCELLED, reason, datetime.now(timezone.utc)
        n += 1
    sync_cache(db, business)
    return n


def complete(db: Session, fu: FollowUp, result: str, note: str | None, actor: User | None) -> FollowUp:
    """Bekleyen takibi tamamlar (sonuç + not); çağıran, iş kurallarını (CRM geçmişi, son görüşme) uygular."""
    fu.status, fu.result, fu.completed_at, fu.completed_by = DONE, result, datetime.now(timezone.utc), actor.id if actor else None
    if note:
        fu.note = ((fu.note + " · ") if fu.note else "") + note.strip()[:500]
    return fu


def to_dict(fu: FollowUp, business: Business | None = None, users: dict[int, str] | None = None, now: datetime | None = None) -> dict:
    users = users or {}
    out = {
        "id": fu.id, "business_id": fu.business_id, "user_id": fu.user_id, "user_name": users.get(fu.user_id) if fu.user_id else None,
        "created_by": fu.created_by, "due_at": fu.due_at, "has_time": fu.has_time, "note": fu.note, "status": fu.status, "result": fu.result,
        "completed_at": fu.completed_at, "date_state": date_state(fu.due_at, now) if fu.status == PENDING else None, "time_passed": time_passed(fu, now),
    }
    if business is not None:
        out["business"] = {"id": business.id, "name": business.name, "phone": business.phone, "crm_stage": business.crm_stage, "crm_owner_id": business.crm_owner_id}
    return out


def counts(db: Session, *, user_id: int | None = None, now: datetime | None = None) -> dict:
    """Bekleyen takip sayıları: gecikmiş / bugün / yarın / bu hafta (bugünden hafta sonuna) / yaklaşan (yarından sonra)."""
    now = now or datetime.now(timezone.utc)
    base = db.query(func.count(FollowUp.id)).filter(FollowUp.status == PENDING)
    if user_id is not None:
        base = base.filter(FollowUp.user_id == user_id)
    out = {}
    for name in ("overdue", "today", "tomorrow", "week", "upcoming"):
        start, end = range_bounds(name, now)
        q = base
        if start is not None:
            q = q.filter(FollowUp.due_at >= start)
        if end is not None:
            q = q.filter(FollowUp.due_at < end)
        out[name] = q.scalar() or 0
    return out
