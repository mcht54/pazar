"""Takipler: oluştur · düzenle · iptal · tamamla · listele (Bugün / Gecikmiş / Yarın / Bu Hafta)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.deps import client_ip, require
from packages.db.base import get_db
from packages.db.models import Business, CrmActivity, FollowUp, User
from services import crm_service
from services import follow_up_service as fus
from services.auth.activity import log_activity
from services.auth.permissions import can

router = APIRouter(prefix="/api/follow-ups", tags=["takipler"])

MAX_PAGE_SIZE = 100


class FollowUpCreate(BaseModel):
    business_id: int
    due_at: str  # 'YYYY-MM-DD' (yalnızca gün) ya da ISO tarih-saat (Europe/Istanbul)
    note: str | None = None
    user_id: int | None = None  # takipten sorumlu (varsayılan: firmanın sorumlusu / oluşturan)


class FollowUpPatch(BaseModel):
    due_at: str | None = None
    note: str | None = None
    user_id: int | None = None
    status: str | None = None  # yalnızca "İptal"

    def provided(self) -> set[str]:
        return set(self.model_fields_set)


class FollowUpDone(BaseModel):
    result: str
    note: str | None = None
    next_follow_up_at: str | None = None


def _get(db: Session, follow_up_id: int) -> FollowUp:
    fu = db.get(FollowUp, follow_up_id)
    if fu is None:
        raise HTTPException(status_code=404, detail="Takip bulunamadı")
    return fu


def _authorize(user: User, fu: FollowUp) -> None:
    """Yönetici/Çalışan her takibi, Stajyer yalnızca kendisine atanmış ya da kendi oluşturduğu takibi değiştirebilir."""
    if not (can(user.role, "crm_assign") or fu.user_id == user.id or fu.created_by == user.id):
        raise HTTPException(status_code=403, detail="Bu takibi değiştirme yetkiniz yok.")


def _log(db: Session, user: User, business: Business, label: str, meta: dict, ip: str | None) -> None:
    now = datetime.now(timezone.utc)
    db.add(CrmActivity(business_id=business.id, type="follow_up", from_stage=None, to_stage=business.crm_stage, note=label, meta=meta,
                       created_by=user.name, user_id=user.id, created_at=now))
    business.crm_last_action, business.crm_updated_at, business.crm_updated_by = label, now, user.id
    log_activity(db, user, "crm_follow_up", business_id=business.id, detail=f"{business.name}: {label}", ip=ip)


def _users(db: Session, rows: list[FollowUp]) -> dict[int, str]:
    ids = {r.user_id for r in rows if r.user_id}
    return {u.id: u.name for u in db.query(User.id, User.name).filter(User.id.in_(ids)).all()} if ids else {}


@router.get("")
def list_follow_ups(
    range: str = "today", status: str = "Bekliyor", scope: str = "mine", user_id: int | None = None, business_id: int | None = None,
    page: int = 1, page_size: int = 25, user: User = Depends(require("crm_use")), db: Session = Depends(get_db),
):
    """Takip listesi (sayfalı). `range`: today | overdue | tomorrow | week | upcoming | all · `status`: Bekliyor | Tamamlandı | İptal | all · `scope`: mine | all."""
    if range not in fus.RANGES:
        raise HTTPException(status_code=422, detail=f"Geçersiz aralık. Geçerli: {', '.join(fus.RANGES)}")
    if status != "all" and status not in fus.STATUSES:
        raise HTTPException(status_code=422, detail=f"Geçersiz durum. Geçerli: {', '.join(fus.STATUSES)} ya da all")
    if scope not in ("mine", "all"):
        raise HTTPException(status_code=422, detail="scope 'mine' ya da 'all' olmalı")
    page, page_size = max(1, page), max(1, min(page_size, MAX_PAGE_SIZE))
    now = datetime.now(timezone.utc)
    query = db.query(FollowUp)
    if status != "all":
        query = query.filter(FollowUp.status == status)
    owner = user_id if user_id is not None else (user.id if scope == "mine" else None)
    if owner is not None:
        query = query.filter(FollowUp.user_id == owner)
    if business_id is not None:
        query = query.filter(FollowUp.business_id == business_id)
    start, end = fus.range_bounds(range, now)
    if start is not None:
        query = query.filter(FollowUp.due_at >= start)
    if end is not None:
        query = query.filter(FollowUp.due_at < end)
    total = query.count()
    rows = query.order_by(FollowUp.due_at, FollowUp.id).offset((page - 1) * page_size).limit(page_size).all()
    businesses = {b.id: b for b in db.query(Business).filter(Business.id.in_({r.business_id for r in rows})).all()} if rows else {}
    users = _users(db, rows)
    return {
        "items": [fus.to_dict(r, businesses.get(r.business_id), users, now) for r in rows], "total": total, "page": page, "page_size": page_size,
        "counts": fus.counts(db, user_id=owner, now=now), "range": range, "status": status, "results": crm_service.FOLLOW_UP_RESULTS,
        "updated_at": now.astimezone(fus.TZ).isoformat(),
    }


@router.post("")
def create_follow_up(payload: FollowUpCreate, request: Request, user: User = Depends(require("crm_use")), db: Session = Depends(get_db)):
    """Takip oluşturur. Firma CRM'de değilse 'Yeni' olarak CRM'e alınır (takip planlamak açık bir CRM işlemidir)."""
    business = db.get(Business, payload.business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="İşletme bulunamadı")
    if payload.user_id is not None:
        if not can(user.role, "crm_assign") and payload.user_id != user.id:
            raise HTTPException(status_code=403, detail="Takibi başka bir kullanıcıya atama yetkiniz yok.")
        target = db.get(User, payload.user_id)
        if target is None or not target.is_active:
            raise HTTPException(status_code=422, detail="Sorumlu kullanıcı bulunamadı veya pasif.")
    try:
        if not crm_service.in_crm(business):
            crm_service.add_to_crm(db, business, "Yeni", None, user=user, ip=client_ip(request))
        fu = fus.create(db, business, payload.due_at, payload.note, owner_id=payload.user_id, actor=user)
        db.flush()
        _log(db, user, business, "Takip planlandı", {"follow_up_id": fu.id, "due_at": fu.due_at.isoformat(), "has_time": fu.has_time}, client_ip(request))
        db.commit()
    except crm_service.CrmError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return fus.to_dict(fu, business, _users(db, [fu]))


@router.patch("/{follow_up_id}")
def patch_follow_up(follow_up_id: int, payload: FollowUpPatch, request: Request, user: User = Depends(require("crm_use")), db: Session = Depends(get_db)):
    """Bekleyen takibin tarih/saatini, notunu ve sorumlusunu değiştirir ya da takibi iptal eder (silinmez)."""
    fu = _get(db, follow_up_id)
    _authorize(user, fu)
    if fu.status != fus.PENDING:
        raise HTTPException(status_code=409, detail="Yalnızca bekleyen takip değiştirilebilir.")
    business = db.get(Business, fu.business_id)
    sent = payload.provided()
    changed: dict = {"follow_up_id": fu.id}
    try:
        if "status" in sent:
            if payload.status != fus.CANCELLED:
                raise crm_service.CrmError(422, "Durum yalnızca 'İptal' olarak değiştirilebilir (tamamlamak için /complete).")
            fu.status, fu.result, fu.completed_at, fu.completed_by = fus.CANCELLED, "İptal edildi", datetime.now(timezone.utc), user.id
            label = "Takip iptal edildi"
        else:
            label = "Takip güncellendi"
            if "due_at" in sent:
                when = crm_service.parse_follow_up(payload.due_at)
                if when is None:
                    raise crm_service.CrmError(422, "Takip tarihi boş olamaz (kaldırmak için iptal edin).")
                fu.due_at, fu.has_time = when, fus._has_time(payload.due_at, when)
                changed["due_at"] = when.isoformat()
            if "note" in sent:
                fu.note = ((payload.note or "").strip()[:1000]) or None
                changed["note"] = fu.note
            if "user_id" in sent:
                if not can(user.role, "crm_assign"):
                    raise HTTPException(status_code=403, detail="Takibi başka bir kullanıcıya atama yetkiniz yok.")
                target = db.get(User, payload.user_id) if payload.user_id else None
                if payload.user_id and (target is None or not target.is_active):
                    raise crm_service.CrmError(422, "Sorumlu kullanıcı bulunamadı veya pasif.")
                fu.user_id = payload.user_id
                changed["user_id"] = payload.user_id
        fus.sync_cache(db, business)
        _log(db, user, business, label, changed, client_ip(request))
        db.commit()
    except crm_service.CrmError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return fus.to_dict(fu, business, _users(db, [fu]))


@router.post("/{follow_up_id}/complete")
def complete_follow_up(follow_up_id: int, payload: FollowUpDone, request: Request, user: User = Depends(require("crm_use")), db: Session = Depends(get_db)):
    """Takibi tamamlar: sonuç + not; istenirse yeni takip tarihi planlanır."""
    fu = _get(db, follow_up_id)
    _authorize(user, fu)
    business = db.get(Business, fu.business_id)
    try:
        crm_service.complete_follow_up_row(db, business, fu, payload.result, payload.note, payload.next_follow_up_at, user=user, ip=client_ip(request))
    except crm_service.CrmError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return fus.to_dict(fu, business, _users(db, [fu]))
