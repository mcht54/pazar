"""Sırların (API anahtarı vb.) veritabanında ŞİFRELİ saklanması.

Anahtar, sunucu ortamındaki API_SECRET_KEY'den türetilir (Fernet: AES-128-CBC + HMAC). Bu değer .env'de/ortamda tutulur, veritabanında
ve arayüzde bulunmaz. Şifreli metin arayüze ASLA gönderilmez; arayüz yalnızca "kayıtlı mı" bilgisini ve son 4 karakteri görür.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from packages.config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("mch-secrets-v1:" + settings.api_secret_key).encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None  # API_SECRET_KEY değişmişse eski sır çözülemez → "kayıtlı değil" gibi davranılır


def mask_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    return "•" * 8 + plain[-4:] if len(plain) > 8 else "•" * len(plain)
