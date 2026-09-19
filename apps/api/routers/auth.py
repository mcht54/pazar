from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.deps import client_ip, current_user_any
from packages.config import settings
from packages.db.base import get_db
from packages.db.models import User
from services.auth import reset as reset_flow
from services.auth import service as auth
from services.auth.activity import log_activity
from services.auth.permissions import ROLE_ICONS, ROLE_LABELS, permissions_for

router = APIRouter(prefix="/api/auth", tags=["kimlik doğrulama"])


class LoginIn(BaseModel):
    identifier: str
    password: str
    remember: bool = False  # 'Beni hatırla': kalıcı çerez (30 gün, kayan); işaretsizse tarayıcı kapanınca biten oturum çerezi


class ForgotIn(BaseModel):
    email: str


class SetPasswordIn(BaseModel):
    token: str
    new_password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def user_payload(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "email": user.email, "username": user.username, "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role), "role_icon": ROLE_ICONS.get(user.role, ""),
        "is_active": user.is_active, "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at, "created_at": user.created_at, "permissions": permissions_for(user.role),
    }


def _http(exc: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        user, token = auth.authenticate(db, payload.identifier, payload.password, ip=client_ip(request), user_agent=request.headers.get("user-agent"), remember=payload.remember)
    except auth.AuthError as exc:
        raise _http(exc) from exc
    # Beni hatırla: kalıcı çerez (max_age). İşaretsiz: oturum çerezi (tarayıcı kapanınca silinir); sunucu tarafı süre yine geçerlidir.
    response.set_cookie(
        auth.COOKIE_NAME, token, max_age=(settings.remember_days * 86400 if payload.remember else None), httponly=True, samesite="lax",
        secure=settings.env != "development", path="/",
    )
    return user_payload(user)


@router.get("/me")
def me(user: User = Depends(current_user_any)):
    return user_payload(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(auth.COOKIE_NAME)
    user = auth.get_session_user(db, token)
    if user:
        log_activity(db, user, "logout", detail="Oturum kapatıldı", ip=client_ip(request), commit=True)
    auth.end_session(db, token)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/change-password")
def change_password(payload: PasswordChangeIn, request: Request, user: User = Depends(current_user_any), db: Session = Depends(get_db)):
    """Kullanıcı kendi şifresini değiştirir (geçici şifreyle giren kullanıcı için zorunlu adım)."""
    try:
        auth.change_own_password(db, user, payload.current_password, payload.new_password, ip=client_ip(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc
    return user_payload(user)


_forgot_hits: dict[str, list[float]] = {}  # IP başına basit hız sınırı (süreç içi): saatte en fazla 10 talep
FORGOT_PER_IP_HOUR = 10


@router.post("/forgot-password")
def forgot_password(payload: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """"Şifremi unuttum": e-posta kayıtlı olsun olmasın AYNI yanıt döner (hesap keşfi yapılamaz). Bağlantı tek kullanımlık ve süreli gönderilir."""
    import time

    ip = client_ip(request) or "?"
    now = time.time()
    hits = [t for t in _forgot_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= FORGOT_PER_IP_HOUR:
        raise HTTPException(status_code=429, detail="Çok fazla talep gönderildi. Lütfen daha sonra tekrar deneyin.")
    _forgot_hits[ip] = hits + [now]
    return {"message": reset_flow.request_reset(db, payload.email, ip=ip)}


@router.get("/reset-token")
def reset_token(token: str, db: Session = Depends(get_db)):
    """Şifre belirleme sayfası bağlantıyı açmadan önce geçerliliğini sorar (token tüketilmez)."""
    return reset_flow.token_status(db, token)


@router.post("/set-password")
def set_password(payload: SetPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Bağlantıdaki token ile yeni şifre belirler (tek kullanımlık). Başarılıysa kullanıcı giriş sayfasına yönlendirilir; oturum açılmaz."""
    try:
        reset_flow.consume(db, payload.token, payload.new_password, ip=client_ip(request))
    except auth.AuthError as exc:
        raise _http(exc) from exc
    return {"ok": True, "message": "Şifreniz belirlendi. Şimdi giriş yapabilirsiniz."}
