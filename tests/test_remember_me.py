"""Beni Hatırla: kalıcı/oturum çerezi, kayan süre, mutlak sınır, çıkışta temizlik."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from packages.config import settings
from packages.db.models import UserSession
from tests.conftest import CSRF_HEADERS, TEST_PASSWORD, make_user


def _login(user, remember=None):
    from apps.api.main import app

    c = TestClient(app, headers=CSRF_HEADERS)
    body = {"identifier": user.email, "password": TEST_PASSWORD}
    if remember is not None:
        body["remember"] = remember
    r = c.post("/api/auth/login", json=body)
    assert r.status_code == 200, r.text
    return c, r


def test_remember_sets_persistent_cookie_and_long_session(seeded_db):
    u = make_user(seeded_db, "calisan")
    c, r = _login(u, remember=True)
    cookie = r.headers["set-cookie"]
    assert f"Max-Age={settings.remember_days * 86400}" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    s = seeded_db.query(UserSession).one()
    assert s.remember is True and timedelta(days=29) < s.expires_at - datetime.now(timezone.utc) <= timedelta(days=30, minutes=1)
    assert c.get("/api/auth/me").status_code == 200


def test_without_remember_cookie_is_a_browser_session_cookie(seeded_db):
    u = make_user(seeded_db, "calisan")
    _, r = _login(u)  # varsayılan: hatırlama yok
    cookie = r.headers["set-cookie"]
    assert "Max-Age" not in cookie and "expires" not in cookie.lower(), "işaretsiz: oturum çerezi (tarayıcı kapanınca silinir)"
    s = seeded_db.query(UserSession).one()
    assert s.remember is False and s.expires_at - datetime.now(timezone.utc) <= timedelta(days=settings.session_days, minutes=1)
    _, r2 = _login(u, remember=False)
    assert "Max-Age" not in r2.headers["set-cookie"]


def test_remembered_session_survives_longer_and_slides(seeded_db):
    u = make_user(seeded_db, "calisan")
    remembered, _ = _login(u, remember=True)
    plain, _ = _login(u, remember=False)
    now = datetime.now(timezone.utc)
    rows = {s.remember: s for s in seeded_db.query(UserSession).all()}
    # 20 gün sonrası: hatırlanan oturum süresi kayan pencere içinde geçerli, hatırlanmayan (7 gün) dolmuş
    rows[True].expires_at = now + timedelta(days=10)
    rows[False].expires_at = now - timedelta(days=1)
    rows[True].last_seen_at = rows[False].last_seen_at = now - timedelta(hours=1)
    seeded_db.commit()
    assert remembered.get("/api/auth/me").status_code == 200
    assert plain.get("/api/auth/me").status_code == 401, "süresi dolan işaretsiz oturum reddedilir"
    seeded_db.expire_all()
    slid = seeded_db.query(UserSession).filter_by(remember=True).one()
    assert slid.expires_at - now > timedelta(days=29), "kullanıldıkça 30 güne uzar (kayan)"


def test_absolute_caps_differ_for_remembered_and_plain_sessions(seeded_db):
    u = make_user(seeded_db, "calisan")
    remembered, _ = _login(u, remember=True)
    plain, _ = _login(u, remember=False)
    now = datetime.now(timezone.utc)
    rows = {s.remember: s for s in seeded_db.query(UserSession).all()}
    rows[True].created_at = now - timedelta(days=settings.remember_max_days - 1)
    rows[False].created_at = now - timedelta(days=settings.session_max_days + 1)
    rows[True].expires_at = rows[False].expires_at = now + timedelta(days=2)
    seeded_db.commit()
    assert remembered.get("/api/auth/me").status_code == 200
    assert plain.get("/api/auth/me").status_code == 401, "işaretsiz oturum mutlak sınırı (30 gün) aşıldı"
    rows[True].created_at = now - timedelta(days=settings.remember_max_days + 1)
    seeded_db.commit()
    assert remembered.get("/api/auth/me").status_code == 401, "hatırlanan oturumun da mutlak sınırı var (90 gün)"


def test_logout_clears_persistent_session(seeded_db):
    u = make_user(seeded_db, "calisan")
    c, _ = _login(u, remember=True)
    token = c.cookies.get("mch_session")
    r = c.post("/api/auth/logout")
    assert r.status_code == 200 and "mch_session" in r.headers["set-cookie"] and ("Max-Age=0" in r.headers["set-cookie"] or "expires" in r.headers["set-cookie"].lower())
    assert seeded_db.query(UserSession).count() == 0, "kalıcı oturum sunucudan silindi"
    from apps.api.main import app

    replay = TestClient(app, headers=CSRF_HEADERS, cookies={"mch_session": token})
    assert replay.get("/api/auth/me").status_code == 401, "çıkıştan sonra eski çerez işe yaramaz"


def test_remember_does_not_weaken_lockout_or_inactive_rules(seeded_db):
    u = make_user(seeded_db, "calisan", is_active=False)
    from apps.api.main import app

    c = TestClient(app, headers=CSRF_HEADERS)
    assert c.post("/api/auth/login", json={"identifier": u.email, "password": TEST_PASSWORD, "remember": True}).status_code == 403
    live = make_user(seeded_db, "calisan")
    remembered, _ = _login(live, remember=True)
    live.is_active = False
    seeded_db.commit()
    assert remembered.get("/api/auth/me").status_code == 401, "pasifleştirilen kullanıcının kalıcı oturumu da geçersiz olur"


# --- Üretim çerez ayarları (HTTPS + aynı kök alan adı): Secure / HttpOnly / SameSite / Domain / Path ---


def _login_cookie(seeded_db, monkeypatch, **overrides):
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)
    _, r = _login(make_user(seeded_db, "calisan"))
    return r.headers["set-cookie"]


def test_cookie_is_secure_outside_development_and_plain_in_development(seeded_db, monkeypatch):
    prod = _login_cookie(seeded_db, monkeypatch, env="production")
    assert "Secure" in prod and "HttpOnly" in prod and "SameSite=lax" in prod and "Path=/" in prod and "Domain" not in prod, prod
    dev = _login_cookie(seeded_db, monkeypatch, env="development")
    assert "Secure" not in dev and "HttpOnly" in dev


def test_cookie_secure_can_be_overridden_and_samesite_none_forces_secure(seeded_db, monkeypatch):
    assert "Secure" not in _login_cookie(seeded_db, monkeypatch, env="production", cookie_secure=False), "HTTP ile prod benzeri deneme için kapatılabilir"
    none = _login_cookie(seeded_db, monkeypatch, env="development", cookie_samesite="none")
    assert "SameSite=none" in none and "Secure" in none, "SameSite=None Secure olmadan tarayıcıca reddedilir"


def test_cookie_domain_is_applied_and_logout_clears_with_same_attributes(seeded_db, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "cookie_domain", "mchttasarim.com.tr")
    c, r = _login(make_user(seeded_db, "calisan"))
    assert "Domain=mchttasarim.com.tr" in r.headers["set-cookie"]
    out = c.post("/api/auth/logout").headers["set-cookie"]
    assert "Domain=mchttasarim.com.tr" in out and "Path=/" in out and "Secure" in out and ("Max-Age=0" in out or "expires" in out.lower()), out


def test_cookie_settings_parse_from_env_strings():
    from packages.config import Settings

    assert Settings(cookie_secure="").cookie_secure is None, "COOKIE_SECURE= (boş) = otomatik"
    assert Settings(cookie_secure="false").cookie_secure is False
    assert Settings(cookie_samesite="STRICT").cookie_samesite == "strict"
    import pytest

    with pytest.raises(ValueError):
        Settings(cookie_samesite="bogus")
