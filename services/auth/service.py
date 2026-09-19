"""Kimlik doğrulama, oturum ve kullanıcı yönetimi iş mantığı."""

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import User, UserSession
from services.auth.activity import log_activity
from services.auth.permissions import ROLES
from services.auth.security import (
    burn_password_check,
    hash_password,
    new_session_token,
    password_problem,
    token_digest,
    verify_password,
)

logger = logging.getLogger(__name__)
COOKIE_NAME = "mch_session"
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 10
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,40}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOGIN_ERROR = "E-posta/kullanıcı adı veya şifre hatalı."


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str, code: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def norm_username(username: str | None) -> str | None:
    value = (username or "").strip().lower()
    return value or None


def find_by_identifier(db: Session, identifier: str) -> User | None:
    ident = (identifier or "").strip().lower()
    if not ident:
        return None
    return db.query(User).filter((func.lower(User.email) == ident) | (func.lower(User.username) == ident)).first()


# ------------------------------------------------------------------ giriş / oturum
def authenticate(db: Session, identifier: str, password: str, *, ip: str | None = None, user_agent: str | None = None, remember: bool = False) -> tuple[User, str]:
    """Başarılıysa (kullanıcı, oturum token'ı). Hatalı girişler kaydedilir; 5 hatalı denemede hesap kısa süre kilitlenir."""
    user = find_by_identifier(db, identifier)
    if user is None:
        burn_password_check(password or "")
        log_activity(db, None, "login_failed", detail=f"Bilinmeyen kullanıcı: {(identifier or '')[:80]}", ip=ip, commit=True)
        raise AuthError(401, LOGIN_ERROR)
    now = _now()
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AuthError(429, f"Çok fazla başarısız deneme. Lütfen {minutes} dakika sonra tekrar deneyin.", "locked")
    if not verify_password(password or "", user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
        log_activity(db, user, "login_failed", detail="Şifre hatalı", ip=ip)
        db.commit()
        raise AuthError(401, LOGIN_ERROR)
    if not user.is_active:  # şifre doğru olduktan sonra söylenir (hesap varlığı sızdırılmaz)
        log_activity(db, user, "login_failed", detail="Pasif hesap girişi engellendi", ip=ip, commit=True)
        raise AuthError(403, "Bu hesap pasif. Lütfen yöneticinizle iletişime geçin.", "inactive")
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    token = new_session_token()
    days = settings.remember_days if remember else settings.session_days
    db.add(UserSession(user_id=user.id, token_hash=token_digest(token), expires_at=now + timedelta(days=days), ip=ip, user_agent=(user_agent or "")[:300], remember=remember))
    log_activity(db, user, "login", detail="Oturum açıldı" + (" (Beni hatırla)" if remember else ""), ip=ip)
    db.commit()
    return user, token


def get_session_user(db: Session, token: str | None) -> User | None:
    """Çerezdeki token geçerliyse kullanıcıyı döndürür ve oturum süresini kaydırır (kayan süre, mutlak üst sınırlı)."""
    if not token:
        return None
    session = db.query(UserSession).filter_by(token_hash=token_digest(token)).one_or_none()
    now = _now()
    if session is None:
        logger.info("Oturum reddedildi: bilinmeyen token (oturum silinmiş/çıkış yapılmış olabilir)")
        return None
    slide = settings.remember_days if session.remember else settings.session_days
    cap = settings.remember_max_days if session.remember else settings.session_max_days
    if session.expires_at <= now:
        logger.info("Oturum reddedildi: süresi doldu (kullanıcı %s, hatırla=%s)", session.user_id, session.remember)
        return None
    if session.created_at + timedelta(days=cap) <= now:
        logger.info("Oturum reddedildi: mutlak süre sınırı (kullanıcı %s, hatırla=%s)", session.user_id, session.remember)
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        logger.info("Oturum reddedildi: kullanıcı yok ya da pasif (kullanıcı %s)", session.user_id)
        return None
    if now - session.last_seen_at > timedelta(minutes=5):
        session.last_seen_at = now
        session.expires_at = min(now + timedelta(days=slide), session.created_at + timedelta(days=cap))
        db.commit()
    return user


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.query(UserSession).filter_by(token_hash=token_digest(token)).delete()
        db.commit()


def revoke_user_sessions(db: Session, user_id: int) -> int:
    n = db.query(UserSession).filter_by(user_id=user_id).delete()
    db.commit()
    return n


# ------------------------------------------------------------------ kullanıcı yönetimi
def _validate_profile(db: Session, *, name: str, email: str, username: str | None, role: str, exclude_id: int | None = None) -> None:
    if not (name or "").strip():
        raise AuthError(422, "Ad Soyad zorunlu.")
    if not _EMAIL_RE.match(email):
        raise AuthError(422, "Geçerli bir e-posta adresi girin.")
    if role not in ROLES:
        raise AuthError(422, f"Geçersiz rol. Geçerli roller: {', '.join(ROLES)}")
    if username is not None and not _USERNAME_RE.match(username):
        raise AuthError(422, "Kullanıcı adı 3-40 karakter olmalı; yalnızca küçük harf, rakam, nokta, tire ve alt çizgi içerebilir.")
    q = db.query(User).filter(func.lower(User.email) == email)
    if exclude_id:
        q = q.filter(User.id != exclude_id)
    if q.first():
        raise AuthError(409, "Bu e-posta adresi zaten kayıtlı.")
    if username:
        q = db.query(User).filter(func.lower(User.username) == username)
        if exclude_id:
            q = q.filter(User.id != exclude_id)
        if q.first():
            raise AuthError(409, "Bu kullanıcı adı zaten kullanılıyor.")


def create_user(db: Session, actor: User | None, *, name: str, email: str, username: str | None, role: str, password: str,
                is_active: bool = True, must_change_password: bool = True, ip: str | None = None) -> User:
    email, username = norm_email(email), norm_username(username)
    _validate_profile(db, name=name, email=email, username=username, role=role)
    problem = password_problem(password)
    if problem:
        raise AuthError(422, problem)
    user = User(name=name.strip(), email=email, username=username, role=role, password_hash=hash_password(password), is_active=is_active,
                must_change_password=must_change_password)
    db.add(user)
    db.flush()
    log_activity(db, actor, "user_create", detail=f"{user.name} ({role}) oluşturuldu", meta={"target_user_id": user.id}, ip=ip)
    db.commit()
    return user


def _active_admins(db: Session) -> int:
    return db.query(User).filter(User.role == "yonetici", User.is_active.is_(True)).count()


def update_user(db: Session, actor: User, user: User, *, name: str | None = None, email: str | None = None, username: str | None = None,
                role: str | None = None, is_active: bool | None = None, ip: str | None = None) -> User:
    new_name = user.name if name is None else name
    new_email = user.email if email is None else norm_email(email)
    new_username = user.username if username is None else norm_username(username)
    new_role = user.role if role is None else role
    _validate_profile(db, name=new_name, email=new_email, username=new_username, role=new_role, exclude_id=user.id)
    if user.id == actor.id and is_active is False:
        raise AuthError(400, "Kendi hesabınızı pasifleştiremezsiniz.")
    if user.id == actor.id and new_role != "yonetici":
        raise AuthError(400, "Kendi yönetici rolünüzü değiştiremezsiniz.")
    losing_admin = user.role == "yonetici" and user.is_active and (new_role != "yonetici" or is_active is False)
    if losing_admin and _active_admins(db) <= 1:
        raise AuthError(400, "Sistemde en az bir aktif yönetici kalmalı.")
    role_changed, old_role = new_role != user.role, user.role
    user.name, user.email, user.username, user.role = new_name.strip(), new_email, new_username, new_role
    if role_changed:
        log_activity(db, actor, "role_change", detail=f"{user.name}: {old_role} → {new_role}", meta={"target_user_id": user.id}, ip=ip)
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        log_activity(db, actor, "user_activate" if is_active else "user_deactivate", detail=user.name, meta={"target_user_id": user.id}, ip=ip)
        if not is_active:
            revoke_user_sessions(db, user.id)
    log_activity(db, actor, "user_update", detail=f"{user.name} düzenlendi", meta={"target_user_id": user.id}, ip=ip)
    db.commit()
    return user


def reset_password(db: Session, actor: User, user: User, new_password: str, *, ip: str | None = None) -> None:
    """Yönetici şifre sıfırlama: mevcut şifre görülmez; yeni geçici şifre atanır, kullanıcı ilk girişte değiştirmek zorundadır."""
    problem = password_problem(new_password)
    if problem:
        raise AuthError(422, problem)
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    revoke_user_sessions(db, user.id)
    log_activity(db, actor, "password_reset", detail=f"{user.name} için şifre sıfırlandı", meta={"target_user_id": user.id}, ip=ip)
    db.commit()


def change_own_password(db: Session, user: User, current_password: str, new_password: str, *, ip: str | None = None) -> None:
    if not verify_password(current_password or "", user.password_hash):
        raise AuthError(400, "Mevcut şifre hatalı.")
    problem = password_problem(new_password)
    if problem:
        raise AuthError(422, problem)
    if verify_password(new_password, user.password_hash):
        raise AuthError(422, "Yeni şifre mevcut şifreyle aynı olamaz.")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    log_activity(db, user, "password_change", detail="Şifre değiştirildi", ip=ip)
    db.commit()
