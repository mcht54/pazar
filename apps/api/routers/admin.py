"""Yönetici alanı: personel aktiviteleri, personel raporları, API ayarları."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.deps import client_ip, require
from packages.db.base import get_db
from packages.db.models import ActivityLog, Business, User
from services.auth.activity import ACTIONS, log_activity
from services.hybrid import api_settings
from services.mail import smtp
from services.sales import pricing
from services.reporting.analysis_stats import PERIODS
from services.reporting.staff_stats import staff_report

router = APIRouter(prefix="/api/admin", tags=["yönetim"])


@router.get("/activity")
def list_activity(
    user_id: int | None = None, action: str | None = None, business_id: int | None = None,
    date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 100, offset: int = 0,
    _: User = Depends(require("activity_view_all")), db: Session = Depends(get_db),
):
    """Tüm personel aktiviteleri (yeniden eskiye): kim · ne zaman · ne yaptı · hangi firma · ayrıntı."""
    limit = max(1, min(limit, 500))
    query = db.query(ActivityLog)
    if user_id is not None:
        query = query.filter(ActivityLog.user_id == user_id)
    if action:
        query = query.filter(ActivityLog.action == action)
    if business_id is not None:
        query = query.filter(ActivityLog.business_id == business_id)
    if date_from:
        query = query.filter(ActivityLog.created_at >= date_from)
    if date_to:
        query = query.filter(ActivityLog.created_at <= date_to)
    total = query.count()
    rows = query.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).offset(offset).limit(limit).all()
    users = {u.id: u.name for u in db.query(User.id, User.name).all()}
    businesses = {b.id: b.name for b in db.query(Business.id, Business.name).filter(Business.id.in_({r.business_id for r in rows if r.business_id})).all()} if rows else {}
    return {
        "total": total,
        "actions": [{"key": k, "label": v} for k, v in ACTIONS.items()],
        "items": [
            {"id": r.id, "created_at": r.created_at, "user_id": r.user_id, "user_name": users.get(r.user_id, "—"), "action": r.action,
             "action_label": ACTIONS.get(r.action, r.action), "business_id": r.business_id, "business_name": businesses.get(r.business_id),
             "detail": r.detail}
            for r in rows
        ],
    }


@router.get("/reports/staff")
def staff_reports(period: str = "today", _: User = Depends(require("staff_reports")), db: Session = Depends(get_db)):
    """Personel bazlı rapor: bugün/hafta/ay/toplam — analiz, arama (Arandı), teklif, kazanılan, CRM ekleme, not. Tümü user_id ile ilişkili gerçek kayıtlar."""
    if period not in PERMISSIONS_PERIODS:
        raise HTTPException(status_code=422, detail=f"Geçersiz dönem. Geçerli: {', '.join(PERMISSIONS_PERIODS)}")
    return staff_report(db, period)


PERMISSIONS_PERIODS = tuple(PERIODS)


# ------------------------------------------------------------------ API ayarları (Google)
class ApiKeyIn(BaseModel):
    api_key: str


class ApiToggleIn(BaseModel):
    enabled: bool


@router.get("/api-settings/google")
def google_state(_: User = Depends(require("api_settings")), db: Session = Depends(get_db)):
    return api_settings.get_state(db)


@router.put("/api-settings/google/key")
def google_save_key(payload: ApiKeyIn, request: Request, user: User = Depends(require("api_settings")), db: Session = Depends(get_db)):
    try:
        state = api_settings.save_key(db, user, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "api_settings_update", detail="Google API anahtarı kaydedildi", ip=client_ip(request), commit=True)
    return state


@router.delete("/api-settings/google/key")
def google_remove_key(request: Request, user: User = Depends(require("api_settings")), db: Session = Depends(get_db)):
    state = api_settings.remove_key(db, user)
    log_activity(db, user, "api_settings_update", detail="Google API anahtarı kaldırıldı", ip=client_ip(request), commit=True)
    return state


@router.post("/api-settings/google/test")
def google_test(request: Request, user: User = Depends(require("api_settings")), db: Session = Depends(get_db)):
    try:
        result = api_settings.test_connection(db, user)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "api_test", detail=("Başarılı: " if result["ok"] else "Başarısız: ") + result["message"], ip=client_ip(request), commit=True)
    return result


@router.put("/api-settings/google/enabled")
def google_toggle(payload: ApiToggleIn, request: Request, user: User = Depends(require("api_settings")), db: Session = Depends(get_db)):
    try:
        state = api_settings.set_enabled(db, user, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "api_toggle", detail="Google API " + ("aktifleştirildi" if payload.enabled else "pasifleştirildi"), ip=client_ip(request), commit=True)
    return state


# ------------------------------------------------------------------ E-posta (SMTP) ayarları
class EmailSettingsIn(BaseModel):
    host: str
    port: int
    username: str | None = None
    password: str | None = None  # boş bırakılırsa kayıtlı şifre korunur
    from_name: str
    from_email: str
    security: str = "tls"


class EmailTestIn(BaseModel):
    to: str


@router.get("/email-settings")
def email_state(_: User = Depends(require("email_settings")), db: Session = Depends(get_db)):
    return smtp.get_state(db)


@router.put("/email-settings")
def email_save(payload: EmailSettingsIn, request: Request, user: User = Depends(require("email_settings")), db: Session = Depends(get_db)):
    try:
        state = smtp.save_settings(db, user, host=payload.host, port=payload.port, username=payload.username, password=payload.password,
                                   from_name=payload.from_name, from_email=payload.from_email, security=payload.security)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "email_settings_update", detail="E-posta (SMTP) ayarları kaydedildi", ip=client_ip(request), commit=True)
    return state


@router.post("/email-settings/test")
def email_test(payload: EmailTestIn, request: Request, user: User = Depends(require("email_settings")), db: Session = Depends(get_db)):
    try:
        result = smtp.send_test(db, user, payload.to)
    except smtp.MailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "email_test", detail=("Başarılı: " if result["ok"] else "Başarısız: ") + result["message"], ip=client_ip(request), commit=True)
    return result


@router.put("/email-settings/enabled")
def email_toggle(payload: ApiToggleIn, request: Request, user: User = Depends(require("email_settings")), db: Session = Depends(get_db)):
    try:
        state = smtp.set_enabled(db, user, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "email_settings_update", detail="E-posta " + ("aktifleştirildi" if payload.enabled else "pasifleştirildi"), ip=client_ip(request), commit=True)
    return state


# ------------------------------------------------------------------ Hizmet ve Fiyat Ayarları
class PriceIn(BaseModel):
    min_price: float | str | None = None
    max_price: float | str | None = None
    default_price: float | str | None = None
    is_active: bool = True


@router.get("/service-prices")
def service_prices(_: User = Depends(require("pricing_manage")), db: Session = Depends(get_db)):
    return {"items": pricing.list_prices(db), "not_priced_label": pricing.NOT_PRICED, "disclaimer": pricing.DISCLAIMER}


@router.put("/service-prices/{service_id}")
def save_service_price(service_id: int, payload: PriceIn, request: Request, user: User = Depends(require("pricing_manage")), db: Session = Depends(get_db)):
    try:
        row = pricing.save_price(db, user, service_id, min_price=payload.min_price, max_price=payload.max_price, default_price=payload.default_price, is_active=payload.is_active)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_activity(db, user, "price_update", detail=f"{row['service_name']}: fiyat aralığı güncellendi", ip=client_ip(request), commit=True)
    return row
