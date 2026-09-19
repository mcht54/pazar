"""Şifre ve oturum güvenliği (yalnızca standart kütüphane).

- Şifreler ASLA düz metin saklanmaz: her kullanıcıya özel rastgele tuzlu scrypt özeti (bellek-yoğun, GPU/ASIC saldırısına dirençli).
- Oturum token'ı rastgele 256 bit; veritabanında yalnızca SHA-256 özeti tutulur (veritabanı sızsa bile token kullanılamaz).
- Karşılaştırmalar sabit zamanlıdır (zamanlama saldırısı).
"""

import base64
import hashlib
import hmac
import re
import secrets

_N, _R, _P = 2**14, 8, 1
_KEYLEN = 32
MIN_PASSWORD_LENGTH = 8


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEYLEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Kullanıcı bulunamadığında da aynı süreyi harcamak için (kullanıcı adı sızdırmayı önler)
_DUMMY_HASH = hash_password("kullanici-yok-sahte-sifre")


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def password_problem(password: str) -> str | None:
    """Şifre politikası ihlali varsa Türkçe açıklama, yoksa None."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Şifre en az {MIN_PASSWORD_LENGTH} karakter olmalı."
    if not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", password) or not re.search(r"\d", password):
        return "Şifre en az bir harf ve bir rakam içermeli."
    return None


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_temp_password() -> str:
    """Okunabilir, politika ile uyumlu rastgele geçici şifre."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    body = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{body}{secrets.choice('23456789')}"
