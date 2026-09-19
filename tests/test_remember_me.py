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
