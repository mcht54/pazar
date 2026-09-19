"""API bağımlılıkları: oturumdaki kullanıcı ve izin kontrolü. YETKİ KONTROLÜ BURADA (sunucuda) yapılır; arayüz yalnızca menüyü gizler."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from packages.db.base import get_db
from packages.db.models import User
from services.auth.permissions import can
from services.auth.service import COOKIE_NAME, get_session_user


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="Oturum açmanız gerekiyor.", headers={"X-Auth": "required"})


def current_user_any(request: Request, db: Session = Depends(get_db)) -> User:
    """Oturum açmış aktif kullanıcı (şifre değişimi beklemesi dahil)."""
    user = get_session_user(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise _unauthenticated()
    request.state.user = user
    return user


def current_user(user: User = Depends(current_user_any)) -> User:
    """Oturum açmış ve (geçici şifresini değiştirmiş) kullanıcı."""
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Devam etmeden önce şifrenizi değiştirmeniz gerekiyor.", headers={"X-Auth": "password-change"})
    return user


def require(permission: str):
    """`Depends(require("crm_use"))`: oturum + izin kontrolü. Yetkisiz: 403."""

    def dependency(user: User = Depends(current_user)) -> User:
        if not can(user.role, permission):
            raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
        return user

    return dependency
