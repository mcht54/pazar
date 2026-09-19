"""E-posta (SMTP) ayarları ve gönderim.

KURALLAR
- SMTP şifresi veritabanında ŞİFRELİ saklanır (services/auth/secrets_store.py); arayüze/loglara/API yanıtlarına ASLA gönderilmez (yalnızca "kayıtlı mı" + son 4 karakter).
- Ayar değiştirilince test sonucu ve aktiflik sıfırlanır; aktifleştirmek için o ayarlarla BAŞARILI bir test e-postası gönderilmiş olmalıdır (parmak izi eşleşmesi).
- E-posta aktif değilken gönderim yapılmaz; çağıran taraf bunu açık bir hata olarak görür (sessizce yutulmaz, uydurma "gönderildi" denmez).
"""

import hashlib
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from packages.db.models import SystemSetting, User
from services.auth.secrets_store import decrypt_secret, encrypt_secret, mask_secret

KEY = "email_smtp"
SECURITIES = {"tls": "TLS (STARTTLS, genellikle 587)", "ssl": "SSL (doğrudan şifreli, genellikle 465)", "none": "Şifresiz (yalnızca yerel/test sunucusu)"}
TIMEOUT = 15
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

STATUS_LABELS = {
    "not_configured": ("🔴", "Ayarlanmadı"),
    "saved": ("🟡", "Ayarlar kayıtlı — test edilmedi"),
    "tested": ("🟢", "Test başarılı — henüz aktif değil"),
    "active": ("✅", "Aktif — e-postalar gönderiliyor"),
    "error": ("⚠️", "Son test başarısız"),
}


class MailError(Exception):
    """Kullanıcıya gösterilebilir Türkçe hata (şifre/ayrıntı sızdırmaz)."""


def _row(db: Session) -> SystemSetting | None:
    return db.get(SystemSetting, KEY)


def _fingerprint(value: dict, password: str | None) -> str:
    parts = [str(value.get(k, "")) for k in ("host", "port", "username", "security", "from_email")] + [password or ""]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def get_state(db: Session) -> dict:
    row = _row(db)
    value = dict(row.value or {}) if row else {}
    password = decrypt_secret(row.secret_encrypted) if row else None
    configured = bool(value.get("host") and value.get("from_email"))
    tested = configured and value.get("last_test_ok") is True and value.get("tested_fingerprint") == _fingerprint(value, password)
    if not configured:
        status = "not_configured"
    elif value.get("enabled") and tested:
        status = "active"
    elif value.get("last_test_ok") is False:
        status = "error"
    elif tested:
        status = "tested"
    else:
        status = "saved"
    icon, label = STATUS_LABELS[status]
    return {
        "status": status, "status_icon": icon, "status_label": label, "configured": configured, "enabled": status == "active",
        "host": value.get("host"), "port": value.get("port"), "username": value.get("username"), "from_name": value.get("from_name"),
        "from_email": value.get("from_email"), "security": value.get("security", "tls"), "securities": [{"key": k, "label": v} for k, v in SECURITIES.items()],
        "has_password": bool(password), "masked_password": mask_secret(password),  # şifrenin kendisi ASLA dönmez
        "last_test_ok": value.get("last_test_ok"), "last_test_at": value.get("last_test_at"), "last_test_message": value.get("last_test_message"),
        "updated_at": row.updated_at if row else None,
    }


def is_active(db: Session) -> bool:
    return get_state(db)["status"] == "active"


def _save(db: Session, user: User | None, *, secret: str | None | bool = False, **updates) -> SystemSetting:
    row = _row(db)
    if row is None:
        row = SystemSetting(key=KEY, value={})
        db.add(row)
    merged = dict(row.value or {})
    merged.update(updates)
    row.value = merged
    if secret is not False:
        row.secret_encrypted = encrypt_secret(secret) if secret else None
    row.updated_by = user.id if user else None
    row.updated_at = datetime.now(timezone.utc)
    return row


def save_settings(db: Session, user: User, *, host: str, port: int, username: str | None, password: str | None, from_name: str, from_email: str, security: str) -> dict:
    host, from_email, username = (host or "").strip(), (from_email or "").strip(), (username or "").strip()
    if not host or any(ch.isspace() for ch in host) or "/" in host:
        raise ValueError("Geçerli bir SMTP sunucu adresi girin (ör. smtp.example.com).")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError("Port 1 ile 65535 arasında olmalı.")
    if not _EMAIL_RE.match(from_email):
        raise ValueError("Geçerli bir gönderen e-posta adresi girin.")
    if security not in SECURITIES:
        raise ValueError("Güvenlik türü tls, ssl veya none olmalı.")
    if not (from_name or "").strip():
        raise ValueError("Gönderen adı boş olamaz.")
    row = _row(db)
    existing = decrypt_secret(row.secret_encrypted) if row else None
    new_secret = existing if password in (None, "") else password  # boş bırakılırsa mevcut şifre korunur
    # ayarlar değiştiği için önceki test/aktiflik geçersiz: yeniden test + aktifleştirme gerekir
    _save(db, user, secret=new_secret, host=host, port=port, username=username or None, from_name=from_name.strip()[:80], from_email=from_email,
          security=security, enabled=False, last_test_ok=None, last_test_at=None, last_test_message=None, tested_fingerprint=None)
    db.commit()
    return get_state(db)


def _credentials(db: Session) -> tuple[dict, str | None]:
    row = _row(db)
    if row is None or not (row.value or {}).get("host"):
        raise MailError("E-posta ayarları yapılmamış.")
    return dict(row.value), decrypt_secret(row.secret_encrypted)


def _explain(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP kullanıcı adı/şifresi kabul edilmedi."
    if isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused)):
        return "Sunucu gönderen ya da alıcı adresini reddetti."
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return "Güvenli bağlantı kurulamadı; güvenlik türünü (TLS/SSL) ve portu kontrol edin."
    if isinstance(exc, (TimeoutError, OSError)):
        return f"SMTP sunucusuna ulaşılamadı ({type(exc).__name__}); adres ve portu kontrol edin."
    return f"E-posta gönderilemedi ({type(exc).__name__})."


def _deliver(value: dict, password: str | None, message: EmailMessage) -> None:
    security, host, port = value.get("security", "tls"), value["host"], int(value.get("port") or 587)
    context = ssl.create_default_context()
    if security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=TIMEOUT)
    with client:
        client.ehlo()
        if security == "tls":
            client.starttls(context=context)
            client.ehlo()
        if value.get("username"):
            client.login(value["username"], password or "")
        client.send_message(message)


def _build(value: dict, to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((value.get("from_name") or "Mchttasarım", value["from_email"]))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def send_mail(db: Session, to: str, subject: str, body: str) -> None:
    """Yalnızca AKTİF (test edilmiş) ayarlarla gönderir; aksi halde MailError."""
    if not is_active(db):
        raise MailError("E-posta ayarları aktif değil.")
    value, password = _credentials(db)
    try:
        _deliver(value, password, _build(value, to, subject, body))
    except Exception as exc:  # noqa: BLE001 — kullanıcıya şifre sızdırmayan Türkçe açıklama verilir
        raise MailError(_explain(exc)) from exc


def send_test(db: Session, user: User, to: str) -> dict:
    """Kayıtlı ayarlarla test e-postası gönderir; sonuç kaydedilir. Başarılıysa ayarlar aktifleştirilebilir."""
    to = (to or "").strip()
    if not _EMAIL_RE.match(to):
        raise ValueError("Geçerli bir test alıcı adresi girin.")
    value, password = _credentials(db)
    try:
        _deliver(value, password, _build(value, to, "Mchttasarım Satış Operasyon — test e-postası", "Bu bir test e-postasıdır. E-posta ayarlarınız çalışıyor.\n\nMchttasarım Satış Operasyon"))
        ok, message = True, f"Test e-postası {to} adresine gönderildi."
    except Exception as exc:  # noqa: BLE001
        ok, message = False, _explain(exc)
    _save(db, user, last_test_ok=ok, last_test_at=datetime.now(timezone.utc).isoformat(), last_test_message=message,
          tested_fingerprint=_fingerprint(value, password) if ok else None)
    if not ok:
        _save(db, user, enabled=False)
    db.commit()
    return {"ok": ok, "message": message, "state": get_state(db)}


def set_enabled(db: Session, user: User, enabled: bool) -> dict:
    state = get_state(db)
    if enabled:
        if not state["configured"]:
            raise ValueError("Önce e-posta ayarlarını kaydedin.")
        if state["status"] not in ("tested", "active"):
            raise ValueError("Aktifleştirmeden önce 'Test e-postası gönder' ile bu ayarların çalıştığını doğrulayın.")
    _save(db, user, enabled=enabled)
    db.commit()
    return get_state(db)
