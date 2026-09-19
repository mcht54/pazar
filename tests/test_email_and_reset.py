"""E-posta (SMTP) ayarları, yeni kullanıcı daveti, "Şifremi unuttum" ve tek kullanımlık şifre bağlantıları.
Gönderim GERÇEK bir SMTP sunucusuna yapılır (yerel aiosmtpd); e-postalar sunucudan okunup bağlantıları oradan çıkarılır."""

import re
import socket
from datetime import datetime, timedelta, timezone
from email import message_from_bytes

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import text

from packages.db.models import PasswordResetToken, SystemSetting, User
from services.auth.security import token_digest, verify_password
from tests.conftest import CSRF_HEADERS, TEST_PASSWORD, logged_in_client, make_user


class Inbox:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append((envelope.rcpt_tos, message_from_bytes(envelope.content)))
        return "250 OK"


@pytest.fixture
def smtp_server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    inbox = Inbox()
    controller = Controller(inbox, hostname="127.0.0.1", port=port)
    controller.start()
    inbox.port = port
    inbox.controller = controller
    yield inbox
    try:
        controller.stop()
    except AssertionError:  # test sunucuyu zaten kapatmış olabilir
        pass


def _settings_body(_port, /, **over):
    body = {"host": "127.0.0.1", "port": _port, "username": None, "password": None, "from_name": "Mchttasarım", "from_email": "satis@example.test", "security": "none"}
    body.update(over)
    return body


def _activate(client, inbox):
    assert client.put("/api/admin/email-settings", json=_settings_body(inbox.port)).status_code == 200
    r = client.post("/api/admin/email-settings/test", json={"to": "test-alici@example.test"}).json()
    assert r["ok"], r
    return client.put("/api/admin/email-settings/enabled", json={"enabled": True}).json()


def _link_from(message):
    body = message.get_payload(decode=True).decode("utf-8")
    match = re.search(r"sifre-belirle\?token=([\w-]+)", body)
    assert match, body
    return match.group(1), body


# ================================================================ E-posta ayarları
def test_email_settings_admin_only_and_secret_never_returned(client, login_as, smtp_server):
    assert login_as("calisan").get("/api/admin/email-settings").status_code == 403
    assert login_as("stajyer").put("/api/admin/email-settings", json=_settings_body(smtp_server.port)).status_code == 403
    st = client.get("/api/admin/email-settings").json()
    assert st["status"] == "not_configured" and st["enabled"] is False
    saved = client.put("/api/admin/email-settings", json=_settings_body(smtp_server.port, username="kullanici", password="SirYeniParola123")).json()
    assert saved["status"] == "saved" and saved["has_password"] and saved["masked_password"].endswith("a123")
    assert "SirYeniParola123" not in str(saved) and "SirYeniParola123" not in str(client.get("/api/admin/email-settings").json())
    from packages.db.base import SessionLocal

    with SessionLocal() as session:
        row = session.get(SystemSetting, "email_smtp")
        assert "SirYeniParola123" not in str(row.value) and row.secret_encrypted and "SirYeniParola123" not in row.secret_encrypted, "şifre veritabanında şifreli"


def test_email_settings_validation(client, smtp_server):
    for bad in ({"host": ""}, {"host": "a b"}, {"port": 0}, {"port": 70000}, {"from_email": "yanlis"}, {"security": "x"}, {"from_name": " "}):
        assert client.put("/api/admin/email-settings", json=_settings_body(smtp_server.port, **bad)).status_code == 422, bad


def test_cannot_activate_before_successful_test(client, smtp_server):
    client.put("/api/admin/email-settings", json=_settings_body(smtp_server.port))
    r = client.put("/api/admin/email-settings/enabled", json={"enabled": True})
    assert r.status_code == 422 and "test" in r.json()["detail"].lower()
    bad = client.put("/api/admin/email-settings", json=_settings_body(1)).json()  # kapalı bir port
    fail = client.post("/api/admin/email-settings/test", json={"to": "a@example.test"}).json()
    assert fail["ok"] is False and fail["state"]["status"] == "error" and bad["status"] == "saved"
    assert client.put("/api/admin/email-settings/enabled", json={"enabled": True}).status_code == 422


def test_test_email_is_really_delivered_and_activation_resets_on_change(client, smtp_server):
    state = _activate(client, smtp_server)
    assert state["status"] == "active" and smtp_server.messages[-1][0] == ["test-alici@example.test"]
    assert "test" in smtp_server.messages[-1][1]["Subject"].lower() and "satis@example.test" in smtp_server.messages[-1][1]["From"]
    changed = client.put("/api/admin/email-settings", json=_settings_body(smtp_server.port, from_email="baska@example.test")).json()
    assert changed["status"] == "saved" and changed["enabled"] is False, "ayar değişince yeniden test gerekir"
    assert client.post("/api/admin/email-settings/test", json={"to": "geçersiz"}).status_code == 422


# ================================================================ davet
def test_invite_sends_link_not_password_and_link_sets_password(client, smtp_server, db):
    r = client.post("/api/admin/users", json={"name": "Yeni Personel", "email": "yeni.personel@example.test", "username": "yenipersonel", "role": "calisan", "send_invite": True})
    assert r.status_code == 409 and "aktif değil" in r.json()["detail"], "e-posta aktif değilken davet gönderilemez ve kullanıcı yarım oluşmaz"
    assert db.query(User).filter_by(email="yeni.personel@example.test").count() == 0
    _activate(client, smtp_server)
    created = client.post("/api/admin/users", json={"name": "Yeni Personel", "email": "yeni.personel@example.test", "username": "yenipersonel", "role": "calisan", "send_invite": True}).json()
    assert created["invite_sent"] is True and "temporary_password" not in created
    rcpt, message = smtp_server.messages[-1]
    assert rcpt == ["yeni.personel@example.test"]
    token, body = _link_from(message)
    assert "şifre" in body.lower() and "48 saat" in body and not re.search(r"[Şş]ifreniz\s*:", body), "e-postada düz şifre yok"
    db.expire_all()
    row = db.query(PasswordResetToken).one()
    assert row.token_hash == token_digest(token) and token not in row.token_hash and row.purpose == "invite" and row.used_at is None
    from apps.api.main import app
    from fastapi.testclient import TestClient

    anon = TestClient(app, headers=CSRF_HEADERS)
    assert anon.get(f"/api/auth/reset-token?token={token}").json() == {"valid": True, "purpose": "invite", "name": "Yeni Personel"}
    assert anon.post("/api/auth/set-password", json={"token": token, "new_password": "kısa"}).status_code == 422
    ok = anon.post("/api/auth/set-password", json={"token": token, "new_password": "YeniSifre2026x"})
    assert ok.status_code == 200
    assert anon.post("/api/auth/login", json={"identifier": "yenipersonel", "password": "YeniSifre2026x"}).status_code == 200
    again = anon.post("/api/auth/set-password", json={"token": token, "new_password": "BaskaSifre2026"})
    assert again.status_code == 400, "token tek kullanımlık"
    assert anon.get(f"/api/auth/reset-token?token={token}").json()["valid"] is False
    user = db.query(User).filter_by(username="yenipersonel").one()
    db.refresh(user)
    assert user.must_change_password is False and verify_password("YeniSifre2026x", user.password_hash)


def test_invite_failure_when_smtp_down_is_reported_not_faked(client, smtp_server, db):
    _activate(client, smtp_server)
    smtp_server.controller.stop()  # sunucu kapandı
    r = client.post("/api/admin/users", json={"name": "Yarım Kalan", "email": "yarim@example.test", "username": "yarim", "role": "stajyer", "send_invite": True}).json()
    assert r["invite_sent"] is False and "ulaşılamadı" in r["invite_error"], "gönderim başarısızsa 'gönderildi' denmez"
    assert db.query(PasswordResetToken).count() == 0, "gönderilemeyen bağlantının token'ı geride bırakılmaz"
    log = client.get("/api/admin/activity?action=invite_sent").json()
    assert log["total"] == 0, "başarısız gönderim 'bağlantı gönderdi' olarak kaydedilmez"


# ================================================================ şifremi unuttum
def test_forgot_password_generic_message_and_single_use_expiring_link(client, smtp_server, db):
    from apps.api.main import app
    from fastapi.testclient import TestClient

    anon = TestClient(app, headers=CSRF_HEADERS)
    staff = make_user(db, "calisan", email="unuttum@example.test", username="unuttum")
    generic = anon.post("/api/auth/forgot-password", json={"email": "unuttum@example.test"}).json()["message"]
    assert generic == "Bu e-posta adresi için işlem başlatıldı."
    assert anon.post("/api/auth/forgot-password", json={"email": "yok@example.test"}).json()["message"] == generic, "kayıtlı olmayan adres aynı yanıtı alır"
    assert db.query(PasswordResetToken).count() == 0 and not smtp_server.messages, "e-posta aktif değilken hiçbir şey gönderilmez ve uydurma 'gönderildi' denmez"
    _activate(client, smtp_server)
    before = len(smtp_server.messages)
    assert anon.post("/api/auth/forgot-password", json={"email": "UNUTTUM@example.test"}).json()["message"] == generic
    assert len(smtp_server.messages) == before + 1
    token, body = _link_from(smtp_server.messages[-1][1])
    assert "60 dakika" in body
    assert anon.post("/api/auth/forgot-password", json={"email": "yok2@example.test"}).json()["message"] == generic and len(smtp_server.messages) == before + 1
    # süre dolumu
    db.expire_all()
    row = db.query(PasswordResetToken).filter_by(token_hash=token_digest(token)).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert anon.post("/api/auth/set-password", json={"token": token, "new_password": "Yeni12345abc"}).status_code == 400
    # yeni talep → yeni token; eskisi zaten geçersiz
    anon.post("/api/auth/forgot-password", json={"email": "unuttum@example.test"})
    token2, _ = _link_from(smtp_server.messages[-1][1])
    assert token2 != token
    assert anon.post("/api/auth/set-password", json={"token": token2, "new_password": "Yeni12345abc"}).status_code == 200
    assert anon.post("/api/auth/login", json={"identifier": staff.email, "password": TEST_PASSWORD}).status_code == 401, "eski şifre artık geçersiz"
    assert anon.post("/api/auth/login", json={"identifier": staff.email, "password": "Yeni12345abc"}).status_code == 200
    assert anon.post("/api/auth/set-password", json={"token": token2, "new_password": "Baska12345abc"}).status_code == 400


def test_forgot_password_rate_limited_per_user_and_ignores_inactive(client, smtp_server, db):
    from apps.api.main import app
    from fastapi.testclient import TestClient

    anon = TestClient(app, headers=CSRF_HEADERS)
    make_user(db, "calisan", email="hiz@example.test", username="hiz")
    make_user(db, "calisan", email="pasif@example.test", username="pasif", is_active=False)
    _activate(client, smtp_server)
    base = len(smtp_server.messages)
    for _ in range(5):
        anon.post("/api/auth/forgot-password", json={"email": "hiz@example.test"})
    assert len(smtp_server.messages) == base + 3, "kullanıcı başına saatte en fazla 3 bağlantı"
    anon.post("/api/auth/forgot-password", json={"email": "pasif@example.test"})
    assert len(smtp_server.messages) == base + 3, "pasif kullanıcıya gönderilmez"


def test_reset_invalidates_existing_sessions_and_invalid_token_is_rejected(client, login_as, smtp_server, db):
    from apps.api.main import app
    from fastapi.testclient import TestClient

    _activate(client, smtp_server)
    staff = login_as("calisan", email="oturum@example.test", username="oturum")
    assert staff.get("/api/auth/me").status_code == 200
    client.post(f"/api/admin/users/{staff.user.id}/send-link")
    token, _ = _link_from(smtp_server.messages[-1][1])
    anon = TestClient(app, headers=CSRF_HEADERS)
    assert anon.post("/api/auth/set-password", json={"token": "uydurma-token", "new_password": "Yeni12345abc"}).status_code == 400
    assert anon.get("/api/auth/reset-token?token=uydurma").json()["valid"] is False
    assert anon.post("/api/auth/set-password", json={"token": token, "new_password": "Yeni12345abc"}).status_code == 200
    assert staff.get("/api/auth/me").status_code == 401, "şifre değişince açık oturumlar kapanır"
    assert login_as("stajyer").post(f"/api/admin/users/{staff.user.id}/send-link").status_code == 403


def test_send_link_requires_active_email_and_active_user(client, db):
    u = make_user(db, "calisan", email="baglanti@example.test", username="baglanti")
    r = client.post(f"/api/admin/users/{u.id}/send-link")
    assert r.status_code == 409 and "aktif değil" in r.json()["detail"]
    off = make_user(db, "calisan", email="kapali@example.test", username="kapali", is_active=False)
    assert client.post(f"/api/admin/users/{off.id}/send-link").status_code == 400


def test_password_reset_tokens_table_has_no_plaintext(client, smtp_server, db):
    _activate(client, smtp_server)
    u = make_user(db, "calisan", email="hash@example.test", username="hashli")
    client.post(f"/api/admin/users/{u.id}/send-link")
    token, _ = _link_from(smtp_server.messages[-1][1])
    stored = db.execute(text("SELECT token_hash FROM password_reset_tokens")).scalars().all()
    assert stored == [token_digest(token)] and token not in stored[0] and len(stored[0]) == 64
