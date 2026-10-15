"""MCHT Panel → bu uygulama: yönetim girişi senkronu (protokol v1; panel tarafı mchttasarim-reklam-ajansi `ajans/vault_sync.py`).

Panelin şifre kasasında bu siteye bağlanan kayıt oluşturulunca/değiştirilince panel `POST /api/mcht/giris-senkron` çağırır:
  X-Mcht-Zaman: unix saniye · X-Mcht-Imza: hex(HMAC-SHA256(PANEL_SYNC_SECRET, zaman + "\\n" + gövde)) · gövde {"gz": base64(gzip(JSON))}
JSON: {v, islem: ping|kaydet, nonce, kimlik, eslesme, kullanici_adi, eposta, ad, sifre}. Yanıt {ok, kimlik} | {ok: false, hata}.

GÜVENLİK: PANEL_SYNC_SECRET yoksa uç kapalıdır (404). İmza sabit zamanlı karşılaştırılır; zaman ±300 sn; nonce Redis'te 10 dk tutulur (tekrar oynatma
reddedilir). Şifre yalnız scrypt özeti olarak yazılır, hiçbir günlüğe/yanıta girmez. Kullanıcı yoksa YÖNETİCİ olarak açılır; varsa rolü değişmez.
Şifre değişince kullanıcının tüm oturumları kapanır."""

import base64
import binascii
import gzip
import hashlib
import hmac
import json
import logging
import time

from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import User
from services.auth import service as auth
from services.auth.activity import log_activity
from services.auth.security import hash_password, password_problem

logger = logging.getLogger(__name__)
WINDOW = 300
_seen_local: dict[str, float] = {}  # Redis yoksa süreç içi yedek


class SyncError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def secret() -> str:
    return (settings.panel_sync_secret or "").strip()


def verify(raw: bytes, stamp: str, signature: str, *, now: float | None = None) -> dict:
    key = secret()
    if len(key) < 32:
        raise SyncError(404, "Bulunamadı.")
    if not stamp.isdigit() or abs((now or time.time()) - int(stamp)) > WINDOW:
        raise SyncError(401, "Zaman damgası geçersiz (sunucu saatleri farklı olabilir).")
    expected = hmac.new(key.encode(), stamp.encode() + b"\n" + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise SyncError(401, "İmza geçersiz: panel ve sitedeki anahtar aynı değil.")
    try:
        data = json.loads(gzip.decompress(base64.b64decode(json.loads(raw)["gz"], validate=True)))
    except (ValueError, KeyError, TypeError, binascii.Error, OSError):
        raise SyncError(400, "Gövde çözülemedi.") from None
    if not isinstance(data, dict) or data.get("v") != 1:
        raise SyncError(400, "Desteklenmeyen protokol sürümü.")
    _check_nonce(str(data.get("nonce") or ""))
    return data


def _check_nonce(nonce: str) -> None:
    if not 16 <= len(nonce) <= 64:
        raise SyncError(400, "Nonce eksik.")
    try:
        import redis

        fresh = redis.Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1).set(f"giris-senkron:{nonce}", 1, nx=True, ex=2 * WINDOW)
    except Exception:  # noqa: BLE001 — Redis yoksa süreç içi kayıt
        now = time.time()
        for k in [k for k, t in _seen_local.items() if now - t > 2 * WINDOW]:
            _seen_local.pop(k, None)
        fresh = nonce not in _seen_local
        _seen_local[nonce] = now
    if not fresh:
        raise SyncError(409, "Bu istek daha önce işlendi (tekrar).")


def _find(db: Session, data: dict) -> User | None:
    kimlik = str(data.get("kimlik") or "")
    if kimlik.isdigit():
        user = db.get(User, int(kimlik))
        if user is not None:
            return user
    for ident in (data.get("eslesme"), data.get("kullanici_adi"), data.get("eposta")):
        user = auth.find_by_identifier(db, str(ident or ""))
        if user is not None:
            return user
    return None


def apply(db: Session, data: dict, *, ip: str | None = None) -> dict:
    """islem=kaydet: kullanıcıyı bulur (kimlik → eski giriş adı → yeni kullanıcı adı/e-posta) ya da yönetici olarak açar."""
    password = data.get("sifre")
    if not isinstance(password, str) or not password:
        raise SyncError(422, "Şifre boş.")
    problem = password_problem(password)
    if problem:
        raise SyncError(422, problem)
    username = auth.norm_username(data.get("kullanici_adi"))
    email = auth.norm_email(data.get("eposta") or "") or None
    user = _find(db, data)
    try:
        if user is None:
            if not email:
                raise SyncError(422, "Bu sitede kullanıcı açmak için e-posta gerekir.")
            name = str(data.get("ad") or username or email.split("@")[0]).strip()[:255]
            user = auth.create_user(db, None, name=name, email=email, username=username, role="yonetici", password=password, must_change_password=False, ip=ip)
            created = True
        else:
            auth._validate_profile(db, name=user.name, email=email or user.email, username=username if username is not None else user.username,
                                   role=user.role, exclude_id=user.id)
            user.email = email or user.email
            if username is not None:
                user.username = username
            user.password_hash = hash_password(password)
            user.must_change_password = False
            user.failed_login_count, user.locked_until, user.is_active = 0, None, True
            created = False
    except auth.AuthError as exc:
        db.rollback()
        raise SyncError(exc.status_code, exc.detail) from None
    log_activity(db, None, "panel_login_sync", detail=f"{user.name}: giriş bilgisi MCHT Panel'den {'oluşturuldu' if created else 'güncellendi'}",
                 meta={"target_user_id": user.id}, ip=ip)
    db.commit()
    auth.revoke_user_sessions(db, user.id)
    return {"ok": True, "kimlik": str(user.id), "olusturuldu": created}
