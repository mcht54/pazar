from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.deps import client_ip, require
from apps.api.routers.auth import user_payload
from packages.db.base import get_db
from packages.db.models import User
from services.auth import reset as reset_flow
from services.auth import service as auth
from services.mail import smtp
from services.auth.permissions import ROLE_LABELS, ROLES
from services.auth.security import generate_temp_password

router = APIRouter(prefix="/api/admin/users", tags=["kullanıcı yönetimi"])


class UserCreate(BaseModel):
    name: str
    email: str
    username: str
    role: str = "calisan"
    password: str | None = None  # boşsa güvenli geçici şifre üretilir
    is_active: bool = True
    send_invite: bool = False  # True: şifre e-postayla gönderilmez; kullanıcıya "şifre belirleme" bağlantısı e-postalanır (e-posta ayarı aktif olmalı)


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    username: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str | None = None  # boşsa güvenli geçici şifre üretilir


def _http(exc: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _get(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return user


@router.get("")
def list_users(actor: User = Depends(require("users_manage")), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.is_active.desc(), User.name).all()
    return {"roles": [{"key": r, "label": ROLE_LABELS[r]} for r in ROLES], "items": [user_payload(u) for u in users]}


@router.post("")
def create_user(payload: UserCreate, request: Request, actor: User = Depends(require("users_manage")), db: Session = Depends(get_db)):
    if payload.send_invite and not smtp.is_active(db):
        raise HTTPException(status_code=409, detail="E-posta ayarları aktif değil; davet bağlantısı gönderilemez. Yönetim → E-posta Ayarları'nı tamamlayın ya da davet olmadan oluşturun.")
    temp = generate_temp_password() if payload.send_invite else (payload.password or generate_temp_password())  # davet: bilinmeyen rastgele şifre (kimse görmez)
    try:
        user = auth.create_user(db, actor, name=payload.name, email=payload.email, username=payload.username, role=payload.role, password=temp,
                                is_active=payload.is_active, must_change_password=True, ip=client_ip(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc
    if payload.send_invite:
        try:
            reset_flow.send_link(db, user, "invite", actor=actor, ip=client_ip(request))
        except smtp.MailError as exc:
            return {**user_payload(user), "invite_sent": False, "invite_error": str(exc)}
        return {**user_payload(user), "invite_sent": True}
    # Geçici şifre YALNIZCA bu yanıtta bir kez döner; sonradan hiçbir yerde görülemez.
    return {**user_payload(user), "temporary_password": temp}


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, request: Request, actor: User = Depends(require("users_manage")), db: Session = Depends(get_db)):
    try:
        user = auth.update_user(db, actor, _get(db, user_id), name=payload.name, email=payload.email, username=payload.username,
                                role=payload.role, is_active=payload.is_active, ip=client_ip(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc
    return user_payload(user)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, payload: PasswordReset, request: Request, actor: User = Depends(require("users_manage")), db: Session = Depends(get_db)):
    temp = payload.new_password or generate_temp_password()
    try:
        auth.reset_password(db, actor, _get(db, user_id), temp, ip=client_ip(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc
    return {"temporary_password": temp, "must_change_password": True}


@router.post("/{user_id}/send-link")
def send_password_link(user_id: int, request: Request, actor: User = Depends(require("users_manage")), db: Session = Depends(get_db)):
    """Kullanıcıya e-postayla tek kullanımlık, süreli "şifre belirleme" bağlantısı gönderir (düz şifre gönderilmez)."""
    user = _get(db, user_id)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Pasif kullanıcıya bağlantı gönderilemez.")
    try:
        reset_flow.send_link(db, user, "reset", actor=actor, ip=client_ip(request))
    except smtp.MailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "message": f"{user.email} adresine şifre belirleme bağlantısı gönderildi."}
