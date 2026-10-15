"""MCHT Panel giriş senkronu (protokol v1): imza/zaman/nonce zorunlu, kullanıcı yoksa yönetici açılır, varsa şifre+giriş adı güncellenir ve
oturumları kapanır; şifre yalnız scrypt özeti olarak durur. Anahtar tanımlı değilse uç yok (404)."""

import base64
import gzip
import hashlib
import hmac
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from packages.config import settings
from packages.db.models import User, UserSession
from services.auth.security import verify_password
from tests.conftest import logged_in_client, make_user

KEY = "k" * 64
URL = "/api/mcht/giris-senkron"


def _send(c, data: dict, *, key=KEY, stamp=None, nonce=None):
    body = json.dumps({"gz": base64.b64encode(gzip.compress(json.dumps({"v": 1, "nonce": nonce or secrets.token_hex(16), **data}).encode())).decode()}).encode()
    stamp = str(stamp or int(time.time()))
    sig = hmac.new(key.encode(), stamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
    return c.post(URL, content=body, headers={"X-Mcht-Zaman": stamp, "X-Mcht-Imza": sig, "Content-Type": "application/json"})


@pytest.fixture
def api(monkeypatch, seeded_db):
    from apps.api.main import app

    monkeypatch.setattr(settings, "panel_sync_secret", KEY)
    return TestClient(app)


def test_disabled_without_secret(seeded_db, monkeypatch):
    from apps.api.main import app

    monkeypatch.setattr(settings, "panel_sync_secret", "")
    assert _send(TestClient(app), {"islem": "ping"}).status_code == 404


def test_signature_time_and_replay_are_enforced(api):
    assert _send(api, {"islem": "ping"}).json()["ok"] is True
    assert _send(api, {"islem": "ping"}, key="x" * 64).status_code == 401
    assert _send(api, {"islem": "ping"}, stamp=int(time.time()) - 1000).status_code == 401
    n = secrets.token_hex(16)
    assert _send(api, {"islem": "ping"}, nonce=n).status_code == 200
    assert _send(api, {"islem": "ping"}, nonce=n).status_code == 409


def test_creates_admin_then_updates_same_user_and_revokes_sessions(api, db):
    r = _send(api, {"islem": "kaydet", "kimlik": None, "eslesme": None, "kullanici_adi": "patron", "eposta": "patron@ornek.test", "ad": "Patron", "sifre": "Ilk-Sifre-2026"})
    assert r.status_code == 200 and r.json()["olusturuldu"] is True
    uid = int(r.json()["kimlik"])
    u = db.get(User, uid)
    assert u.role == "yonetici" and u.username == "patron" and not u.must_change_password and verify_password("Ilk-Sifre-2026", u.password_hash)
    c = logged_in_client(u, "Ilk-Sifre-2026")
    assert db.query(UserSession).filter_by(user_id=uid).count() == 1
    r = _send(api, {"islem": "kaydet", "kimlik": str(uid), "eslesme": "patron", "kullanici_adi": "mucahit", "eposta": "patron@ornek.test", "ad": "x", "sifre": "Yeni-Sifre-2027"})
    assert r.json() == {"ok": True, "kimlik": str(uid), "olusturuldu": False}
    db.expire_all()
    u = db.get(User, uid)
    assert u.username == "mucahit" and u.role == "yonetici" and verify_password("Yeni-Sifre-2027", u.password_hash) and "Yeni-Sifre" not in u.password_hash
    assert db.query(UserSession).filter_by(user_id=uid).count() == 0 and c.get("/api/auth/me").status_code == 401


def test_existing_user_found_by_email_keeps_role_and_policy_is_applied(api, db):
    staff = make_user(db, "calisan", email="eleman@ornek.test")
    r = _send(api, {"islem": "kaydet", "kullanici_adi": None, "eposta": "eleman@ornek.test", "sifre": "kisa"})
    assert r.status_code == 422 and "kisa" not in r.text
    r = _send(api, {"islem": "kaydet", "kullanici_adi": None, "eposta": "eleman@ornek.test", "sifre": "Uzun-Sifre-123"})
    assert r.json()["kimlik"] == str(staff.id)
    db.expire_all()
    assert db.get(User, staff.id).role == "calisan" and verify_password("Uzun-Sifre-123", db.get(User, staff.id).password_hash)
