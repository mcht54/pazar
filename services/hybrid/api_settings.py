"""Google API ayarları (yönetici paneli): anahtarı şifreli saklama, bağlantı testi, aktifleştirme.

KURALLAR
- Anahtar arayüze/loglara ASLA açık gönderilmez; yalnızca "kayıtlı mı" ve son 4 karakter görünür.
- Bu ayar mevcut çalışan veri kaynaklarını (Google Haritalar okuma, Bing, web sitesi) DEVRE DIŞI BIRAKMAZ. API aktifse yalnızca ek/tamamlayıcı
  bir kaynak olur (services/research/google_api.py + pipeline.py). API kapalı/başarısız olduğunda sistem eskisi gibi çalışır.
- Bağlantı testi ve aktifleştirme yalnızca yönetici tarafından, bilinçli olarak yapılır; anahtar kaydedildi diye Google'a istek atılmaz.
"""

from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import SystemSetting, User
from services.auth.secrets_store import decrypt_secret, encrypt_secret, mask_secret

KEY = "google_api"
PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
TEST_TIMEOUT = 10.0

# durum kodu → (simge, Türkçe etiket)
STATUS_LABELS = {
    "not_connected": ("🔴", "Bağlı değil"),
    "saved": ("🟡", "Anahtar kayıtlı — test edilmedi"),
    "connected": ("🟢", "Bağlantı başarılı — henüz aktif değil"),
    "active": ("✅", "Aktif — tamamlayıcı kaynak olarak kullanılıyor"),
    "error": ("⚠️", "Bağlantı hatası"),
}


def _row(db: Session) -> SystemSetting | None:
    return db.get(SystemSetting, KEY)


def _stored_key(db: Session) -> str | None:
    row = _row(db)
    return decrypt_secret(row.secret_encrypted) if row else None


def effective_key(db: Session) -> tuple[str | None, str]:
    """(anahtar, kaynak): önce panelde kayıtlı anahtar; yoksa ortam değişkeni GOOGLE_PLACES_API_KEY (kaynak: 'environment')."""
    stored = _stored_key(db)
    if stored:
        return stored, "panel"
    if settings.google_places_api_key:
        return settings.google_places_api_key, "environment"
    return None, "none"


def get_state(db: Session) -> dict:
    row = _row(db)
    value = dict(row.value or {}) if row else {}
    key, source = effective_key(db)
    enabled = bool(value.get("enabled")) and bool(key)
    last_ok, last_at = value.get("last_test_ok"), value.get("last_test_at")
    if not key:
        status = "not_connected"
    elif enabled and last_ok is not False:
        status = "active"
    elif last_ok is False:
        status = "error"
    elif last_ok is True:
        status = "connected"
    else:
        status = "saved"
    icon, label = STATUS_LABELS[status]
    return {
        "status": status, "status_icon": icon, "status_label": label,
        "has_key": bool(key), "key_source": source, "masked_key": mask_secret(key),  # anahtarın kendisi ASLA dönmez
        "enabled": enabled, "last_test_ok": last_ok, "last_test_at": last_at, "last_test_message": value.get("last_test_message"),
        "updated_at": row.updated_at if row else None,
        "note": "Google API aktif olsa bile mevcut kaynaklar (Google Haritalar okuma, Bing, web sitesi) çalışmaya devam eder; API yalnızca eksik bilgileri tamamlar.",
    }


def _save(db: Session, user: User | None, *, secret: str | None | bool = False, **value_updates) -> SystemSetting:
    row = _row(db)
    if row is None:
        row = SystemSetting(key=KEY, value={})
        db.add(row)
    merged = dict(row.value or {})
    merged.update(value_updates)
    row.value = merged
    if secret is not False:
        row.secret_encrypted = encrypt_secret(secret) if secret else None
    row.updated_by = user.id if user else None
    row.updated_at = datetime.now(timezone.utc)
    return row


def save_key(db: Session, user: User, api_key: str) -> dict:
    api_key = (api_key or "").strip()
    if len(api_key) < 20 or any(ch.isspace() for ch in api_key):
        raise ValueError("Geçerli bir API anahtarı girin (boşluk içermeyen, en az 20 karakter).")
    # yeni anahtar kaydedilince eski test sonucu ve aktiflik sıfırlanır: bilinçli test + aktifleştirme gerekir
    _save(db, user, secret=api_key, enabled=False, last_test_ok=None, last_test_at=None, last_test_message=None)
    db.commit()
    return get_state(db)


def remove_key(db: Session, user: User) -> dict:
    _save(db, user, secret=None, enabled=False, last_test_ok=None, last_test_at=None, last_test_message=None)
    db.commit()
    return get_state(db)


def _http_post(url: str, *, json: dict, headers: dict) -> httpx.Response:
    return httpx.post(url, json=json, headers=headers, timeout=TEST_TIMEOUT)


def _explain(status_code: int, body: str) -> str:
    text = (body or "").lower()
    if status_code == 200:
        return "Bağlantı başarılı: Google Places API anahtarı kabul edildi."
    if status_code == 400 and ("api key not valid" in text or "api_key_invalid" in text):
        return "API anahtarı geçersiz. Anahtarı Google Cloud'dan kontrol edin."
    if status_code == 403 and ("has not been used" in text or "disabled" in text or "service_disabled" in text):
        return "Bu proje için Places API (New) etkin değil. Google Cloud'da 'Places API (New)' hizmetini etkinleştirin."
    if status_code == 403:
        return "İstek reddedildi (403): anahtar kısıtlamaları, faturalandırma veya yetki sorunu olabilir."
    if status_code == 429:
        return "Google istek sınırına ulaşıldı (429). Bir süre sonra tekrar deneyin."
    return f"Beklenmeyen yanıt (HTTP {status_code})."


def test_connection(db: Session, user: User) -> dict:
    """Kayıtlı anahtarla Google'a TEK bir küçük istek atar (1 sonuç, yalnızca kimlik alanı). Sonuç kaydedilir; başarısızlık sistemi etkilemez."""
    key, _ = effective_key(db)
    if not key:
        raise ValueError("Önce bir API anahtarı kaydedin.")
    try:
        response = _http_post(
            settings.google_places_search_url, json={"textQuery": "Adapazarı", "pageSize": 1, "languageCode": "tr"},
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.id"},
        )
        ok, message = response.status_code == 200, _explain(response.status_code, response.text[:500])
    except httpx.RequestError as exc:
        ok, message = False, f"Google'a ulaşılamadı ({type(exc).__name__}). İnternet bağlantısını kontrol edin."
    _save(db, user, last_test_ok=ok, last_test_at=datetime.now(timezone.utc).isoformat(), last_test_message=message)
    if not ok:
        _save(db, user, enabled=False)  # hatalı anahtarla aktif kalınmaz
    db.commit()
    return {"ok": ok, "message": message, "state": get_state(db)}


def set_enabled(db: Session, user: User, enabled: bool) -> dict:
    state = get_state(db)
    if enabled:
        if not state["has_key"]:
            raise ValueError("Aktifleştirmek için önce API anahtarı kaydedin.")
        if state["last_test_ok"] is not True:
            raise ValueError("Aktifleştirmeden önce 'Bağlantıyı Test Et' ile bağlantının başarılı olduğunu doğrulayın.")
    _save(db, user, enabled=enabled)
    db.commit()
    return get_state(db)


def active_key(db: Session) -> str | None:
    """Araştırma hattının kullanacağı anahtar: yalnızca API AKTİFSE; aksi halde None (mevcut kaynaklarla devam)."""
    state = get_state(db)
    if state["status"] != "active":
        return None
    key, _ = effective_key(db)
    return key
