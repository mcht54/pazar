"""Şifre belirleme (yeni kullanıcı daveti) ve "Şifremi unuttum" akışları.

- Bağlantıdaki token rastgele üretilir (secrets.token_urlsafe); veritabanında YALNIZCA SHA-256 özeti saklanır.
- Token tek kullanımlıktır, süreli çıkar (sıfırlama 60 dk, davet 48 sa). Yeni token üretilince aynı kullanıcının eski kullanılmamış token'ları geçersiz olur.
- E-postayla asla düz şifre gönderilmez. Şifre bağlantı üzerinden kullanıcının kendisi tarafından belirlenir.
- "Şifremi unuttum" yanıtı, e-posta kayıtlı olsun olmasın AYNIDIR (hesap keşfi yapılamaz). Saatte kullanıcı başına en fazla 3 istek.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import PasswordResetToken, User
from services.auth import service as auth
from services.auth.activity import log_activity
from services.auth.security import hash_password, password_problem, token_digest
from services.mail import smtp

RESET_MINUTES = 60
INVITE_HOURS = 48
MAX_REQUESTS_PER_HOUR = 3
GENERIC_MESSAGE = "Bu e-posta adresi için işlem başlatıldı."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue_token(db: Session, user: User, purpose: str, *, ip: str | None = None) -> str:
    """Yeni token üretir (ham değer yalnızca dönüşte vardır), eski açık token'ları geçersiz kılar."""
    now = _now()
    for old in db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).all():
        old.used_at = now
    raw = secrets.token_urlsafe(32)
    ttl = timedelta(hours=INVITE_HOURS) if purpose == "invite" else timedelta(minutes=RESET_MINUTES)
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_digest(raw), purpose=purpose, expires_at=now + ttl, ip=ip))
    db.flush()
    return raw


def _link(raw: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}/sifre-belirle?token={raw}"


def _mail_body(user: User, raw: str, purpose: str) -> tuple[str, str]:
    if purpose == "invite":
        return ("Mchttasarım Satış Operasyon — hesabınız oluşturuldu",
                f"Merhaba {user.name},\n\nMchttasarım Satış Operasyon uygulaması için hesabınız oluşturuldu.\n"
                f"Şifrenizi belirlemek için aşağıdaki bağlantıyı kullanın (bağlantı {INVITE_HOURS} saat geçerlidir ve yalnızca bir kez kullanılabilir):\n\n{_link(raw)}\n\n"
                f"Kullanıcı adınız: {user.username or user.email}\n\nBu e-postayı beklemiyorsanız dikkate almayın.")
    return ("Mchttasarım Satış Operasyon — şifre sıfırlama",
            f"Merhaba {user.name},\n\nŞifrenizi sıfırlamak için bir talep alındı. Yeni şifre belirlemek için aşağıdaki bağlantıyı kullanın "
            f"(bağlantı {RESET_MINUTES} dakika geçerlidir ve yalnızca bir kez kullanılabilir):\n\n{_link(raw)}\n\n"
            "Bu talebi siz yapmadıysanız bu e-postayı dikkate almayın; şifreniz değişmez.")


def send_link(db: Session, user: User, purpose: str, *, actor: User | None = None, ip: str | None = None) -> None:
    """Token üretip e-posta gönderir. E-posta aktif değilse ya da gönderim başarısızsa MailError (token da geri alınır)."""
    if not smtp.is_active(db):
        raise smtp.MailError("E-posta ayarları aktif değil; bağlantı gönderilemedi. Yönetim → E-posta Ayarları'ndan ayarları tamamlayın.")
    raw = issue_token(db, user, purpose, ip=ip)
    subject, body = _mail_body(user, raw, purpose)
    try:
        smtp.send_mail(db, user.email, subject, body)
    except smtp.MailError:
        db.rollback()
        raise
    log_activity(db, actor, "invite_sent" if purpose == "invite" else "password_reset",
                 detail=f"{user.name}: şifre belirleme bağlantısı e-postayla gönderildi", meta={"target_user_id": user.id}, ip=ip)
    db.commit()


def request_reset(db: Session, email: str, *, ip: str | None = None) -> str:
    """"Şifremi unuttum". Döndürdüğü mesaj HER ZAMAN aynıdır. Gerçekte yalnızca aktif kullanıcıya, e-posta aktifse ve hız sınırı aşılmadıysa gönderilir."""
    user = db.query(User).filter(User.email == auth.norm_email(email)).first()
    if user is None or not user.is_active:
        return GENERIC_MESSAGE
    recent = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id, PasswordResetToken.created_at >= _now() - timedelta(hours=1)).count()
    if recent >= MAX_REQUESTS_PER_HOUR:
        return GENERIC_MESSAGE
    try:
        send_link(db, user, "reset", actor=None, ip=ip)
        log_activity(db, user, "password_forgot", detail="Şifremi unuttum: bağlantı gönderildi", ip=ip, commit=True)
    except smtp.MailError as exc:
        log_activity(db, user, "password_forgot", detail=f"Şifremi unuttum: bağlantı gönderilemedi ({exc})", ip=ip, commit=True)
    return GENERIC_MESSAGE


def _valid(db: Session, raw: str) -> PasswordResetToken | None:
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_digest(raw or "")).first()
    if row is None or row.used_at is not None or row.expires_at <= _now():
        return None
    return row


def token_status(db: Session, raw: str) -> dict:
    row = _valid(db, raw)
    if row is None:
        return {"valid": False, "message": "Bağlantı geçersiz, süresi dolmuş ya da daha önce kullanılmış."}
    user = db.get(User, row.user_id)
    return {"valid": True, "purpose": row.purpose, "name": user.name if user else None}


def consume(db: Session, raw: str, new_password: str, *, ip: str | None = None) -> User:
    """Token geçerliyse yeni şifreyi atar, token'ı kullanılmış yapar, tüm oturumları kapatır."""
    row = _valid(db, raw)
    if row is None:
        raise auth.AuthError(400, "Bağlantı geçersiz, süresi dolmuş ya da daha önce kullanılmış.")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise auth.AuthError(400, "Bağlantı geçersiz, süresi dolmuş ya da daha önce kullanılmış.")
    problem = password_problem(new_password)
    if problem:
        raise auth.AuthError(422, problem)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    row.used_at = _now()
    auth.revoke_user_sessions(db, user.id)
    log_activity(db, user, "password_set", detail="Şifre bağlantısıyla şifre belirlendi", ip=ip)
    db.commit()
    return user
