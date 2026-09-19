"""Çok kullanıcılı giriş, roller/yetkiler (sunucu tarafında), kullanıcı yönetimi, şifre, oturum, aktivite geçmişi, kullanıcıya bağlı CRM ve analiz."""

import pytest
from fastapi.testclient import TestClient

from packages.db.models import ActivityLog, AnalysisJob, Business, CrmActivity, User, UserSession
from services.auth.permissions import CALISAN, PERMISSIONS, ROLES, STAJYER, YONETICI, can
from services.auth.security import hash_password, password_problem, token_digest, verify_password
from tests.conftest import CSRF_HEADERS, TEST_PASSWORD, make_user
from tests.test_sales_features import _analyzed_business


# ================================================================ ŞİFRE GÜVENLİĞİ
def test_passwords_are_hashed_salted_and_verified():
    h1, h2 = hash_password("Sifre12345"), hash_password("Sifre12345")
    assert h1 != h2 and "Sifre12345" not in h1 and h1.startswith("scrypt$"), "düz metin saklanmamalı; her özet farklı tuz içermeli"
    assert verify_password("Sifre12345", h1) and not verify_password("sifre12345", h1) and not verify_password("x", None)


def test_password_policy():
    assert password_problem("kisa1") and password_problem("sadeceharflerburada") and password_problem("12345678901")
    assert password_problem("Guclu12345") is None


def test_plain_password_never_stored_in_database(db, admin_user):
    row = db.query(User).filter_by(id=admin_user.id).one()
    assert TEST_PASSWORD not in (row.password_hash or "") and row.password_hash.startswith("scrypt$")


# ================================================================ GİRİŞ / OTURUM
def test_protected_endpoints_require_login(anon_client):
    for method, path in [("get", "/api/businesses"), ("get", "/api/regions"), ("get", "/api/sectors"), ("get", "/api/crm"), ("get", "/api/crm/summary"),
                         ("get", "/api/dashboard/today"), ("get", "/api/reports/analysis"), ("get", "/api/guides"), ("get", "/api/admin/users"),
                         ("get", "/api/admin/activity"), ("get", "/api/admin/api-settings/google"), ("get", "/api/businesses/1")]:
        assert getattr(anon_client, method)(path).status_code == 401, path
    assert anon_client.post("/api/discovery/jobs", json={"region_id": 1, "sector_id": 1, "target_count": 1}).status_code == 401
    assert anon_client.post("/api/businesses/1/crm", json={"stage": "Aranacak"}).status_code == 401
    assert anon_client.post("/api/businesses/export", json={"ids": [1], "format": "csv"}).status_code == 401
    assert anon_client.get("/api/health").status_code == 200, "sağlık kontrolü herkese açık kalır"


def test_login_success_sets_httponly_cookie_and_returns_profile(anon_client, admin_user):
    r = anon_client.post("/api/auth/login", json={"identifier": "yonetici@example.test", "password": TEST_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "yonetici" and body["role_label"] == "Yönetici" and "password_hash" not in body and "users_manage" in body["permissions"]
    cookie = r.headers["set-cookie"].lower()
    assert "mch_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert anon_client.get("/api/auth/me").json()["email"] == "yonetici@example.test", "oturum sonraki isteklerde (yenilemede) korunur"


def test_login_by_username_and_case_insensitive_email(anon_client, admin_user):
    assert anon_client.post("/api/auth/login", json={"identifier": "YONETICI", "password": TEST_PASSWORD}).status_code == 200
    anon_client.post("/api/auth/logout")
    assert anon_client.post("/api/auth/login", json={"identifier": "Yonetici@Example.TEST", "password": TEST_PASSWORD}).status_code == 200


def test_wrong_password_and_unknown_user_get_same_generic_error(anon_client, admin_user):
    a = anon_client.post("/api/auth/login", json={"identifier": "yonetici", "password": "Yanlis12345"})
    b = anon_client.post("/api/auth/login", json={"identifier": "yok-boyle-biri", "password": "Yanlis12345"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json(), "hesap varlığı sızdırılmamalı"


def test_account_locks_after_repeated_failures(anon_client, admin_user):
    for _ in range(5):
        anon_client.post("/api/auth/login", json={"identifier": "yonetici", "password": "Yanlis12345"})
    r = anon_client.post("/api/auth/login", json={"identifier": "yonetici", "password": TEST_PASSWORD})
    assert r.status_code == 429 and "dakika" in r.json()["detail"], "5 hatalı denemeden sonra doğru şifre bile kısa süre reddedilir"


def test_logout_invalidates_session(client):
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401 and client.get("/api/businesses").status_code == 401


def test_session_token_stored_only_as_hash(client, db):
    row = db.query(UserSession).one()
    token = client.cookies.get("mch_session")
    assert token and row.token_hash == token_digest(token) and token not in row.token_hash


def test_expired_session_is_rejected(client, db):
    from datetime import datetime, timedelta, timezone

    row = db.query(UserSession).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_csrf_header_required_for_unsafe_methods(admin_user):
    from apps.api.main import app

    bare = TestClient(app)  # X-Requested-With yok
    assert bare.post("/api/auth/login", json={"identifier": "yonetici", "password": TEST_PASSWORD}).status_code == 403
    assert bare.get("/api/health").status_code == 200


def test_inactive_user_cannot_login_but_records_are_kept(anon_client, db, seeded_db):
    user = make_user(seeded_db, "calisan", email="pasif@example.test", username="pasif", is_active=False)
    r = anon_client.post("/api/auth/login", json={"identifier": "pasif", "password": TEST_PASSWORD})
    assert r.status_code == 403 and "pasif" in r.json()["detail"].lower()
    assert db.query(User).filter_by(id=user.id).count() == 1


def test_deactivating_a_user_revokes_open_sessions_and_keeps_history(client, login_as, db):
    staff = login_as("calisan", name="Ahmet Yılmaz")
    bid = _analyzed_business(client, db, name="Aktivite Kliniği")
    assert staff.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak", "note": "ilk arama"}).status_code == 200
    r = client.patch(f"/api/admin/users/{staff.user.id}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert staff.get("/api/auth/me").status_code == 401, "pasifleştirilen kullanıcının açık oturumu kapanır"
    hist = client.get(f"/api/businesses/{bid}").json()["crm_history"]
    assert hist[0]["user_name"] == "Ahmet Yılmaz", "eski CRM kayıtları ve işlemi yapan kişi korunur"


# ================================================================ ROLLER / YETKİ (SUNUCU TARAFI)
def test_permission_matrix_matches_requirements():
    assert set(ROLES) == {YONETICI, CALISAN, STAJYER}
    for role in ROLES:
        for perm in ("search", "analyze", "view_business", "crm_use", "guides", "dashboard"):
            assert can(role, perm), (role, perm)
    for perm in ("users_manage", "activity_view_all", "staff_reports", "api_settings"):
        assert can(YONETICI, perm) and not can(CALISAN, perm) and not can(STAJYER, perm), perm
    assert can(CALISAN, "sales_note") and can(CALISAN, "export") and not can(STAJYER, "sales_note") and not can(STAJYER, "export")


@pytest.mark.parametrize("role", [CALISAN, STAJYER])
def test_non_admin_cannot_access_admin_apis(login_as, role):
    c = login_as(role)
    for method, path, body in [
        ("get", "/api/admin/users", None), ("post", "/api/admin/users", {"name": "X", "email": "x@x.test", "username": "xx1", "role": "calisan"}),
        ("patch", "/api/admin/users/1", {"role": "yonetici"}), ("post", "/api/admin/users/1/reset-password", {}),
        ("get", "/api/admin/activity", None), ("get", "/api/admin/reports/staff", None), ("get", "/api/admin/api-settings/google", None),
        ("put", "/api/admin/api-settings/google/key", {"api_key": "x" * 30}), ("post", "/api/admin/api-settings/google/test", None),
        ("put", "/api/admin/api-settings/google/enabled", {"enabled": True}),
    ]:
        r = getattr(c, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (role, method, path, r.status_code)


def test_employee_can_use_sales_operations_and_intern_gets_limits(client, login_as, db):
    bid = _analyzed_business(client, db, name="Yetki Kliniği")
    employee, intern = login_as("calisan"), login_as("stajyer")
    for c in (employee, intern):
        assert c.get("/api/businesses").status_code == 200 and c.get(f"/api/businesses/{bid}").status_code == 200
        assert c.get("/api/crm").status_code == 200 and c.get("/api/dashboard/today").status_code == 200 and c.get("/api/guides").status_code == 200
        assert c.get("/api/reports/analysis").status_code == 200 and c.get("/api/regions").status_code == 200
    assert employee.get(f"/api/businesses/{bid}/sales-note").status_code == 200
    assert intern.get(f"/api/businesses/{bid}/sales-note").status_code == 403
    assert employee.post("/api/businesses/export", json={"ids": [bid], "format": "csv"}).status_code == 200
    assert intern.post("/api/businesses/export", json={"ids": [bid], "format": "csv"}).status_code == 403
    for c in (employee, intern):
        assert c.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak"}).status_code in (200, 409)
        assert c.patch(f"/api/businesses/{bid}/crm", json={"staff_note": "not"}).status_code == 200


# ================================================================ KULLANICI YÖNETİMİ
def test_admin_creates_user_with_temp_password_forced_change_and_unique_email(client, anon_client):
    r = client.post("/api/admin/users", json={"name": "Ayşe Demir", "email": "Ayse@Example.test", "username": "ayse", "role": "calisan", "password": "Gecici12345"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "ayse@example.test" and body["role"] == "calisan" and body["must_change_password"] is True and body["temporary_password"] == "Gecici12345"
    dup = client.post("/api/admin/users", json={"name": "Başka", "email": "ayse@example.test", "username": "ayse2", "role": "stajyer"})
    assert dup.status_code == 409 and "e-posta" in dup.json()["detail"].lower()
    dup2 = client.post("/api/admin/users", json={"name": "Başka", "email": "baska@example.test", "username": "AYSE", "role": "stajyer"})
    assert dup2.status_code == 409
    listing = client.get("/api/admin/users").json()
    row = next(u for u in listing["items"] if u["email"] == "ayse@example.test")
    assert "password_hash" not in row and "temporary_password" not in row, "şifre bilgisi listede asla görünmez"
    # geçici şifreyle giriş → şifre değişene kadar diğer API'ler kapalı
    anon_client.post("/api/auth/login", json={"identifier": "ayse", "password": "Gecici12345"})
    assert anon_client.get("/api/auth/me").json()["must_change_password"] is True
    assert anon_client.get("/api/businesses").status_code == 403
    assert anon_client.post("/api/auth/change-password", json={"current_password": "Gecici12345", "new_password": "YeniSifre123"}).status_code == 200
    assert anon_client.get("/api/businesses").status_code == 200


def test_admin_generates_secure_temp_password_when_omitted(client):
    r = client.post("/api/admin/users", json={"name": "Otomatik", "email": "oto@example.test", "username": "oto", "role": "stajyer"}).json()
    assert password_problem(r["temporary_password"]) is None and len(r["temporary_password"]) >= 10


def test_user_validation(client):
    bad = client.post("/api/admin/users", json={"name": "", "email": "x@x.test", "username": "abc", "role": "calisan", "password": "Gecici12345"})
    assert bad.status_code == 422
    assert client.post("/api/admin/users", json={"name": "A", "email": "gecersiz", "username": "abc", "role": "calisan", "password": "Gecici12345"}).status_code == 422
    assert client.post("/api/admin/users", json={"name": "A", "email": "a@a.test", "username": "abc", "role": "patron", "password": "Gecici12345"}).status_code == 422
    assert client.post("/api/admin/users", json={"name": "A", "email": "a@a.test", "username": "abc", "role": "calisan", "password": "kisa"}).status_code == 422


def test_admin_edits_user_and_changes_role_with_audit(client, login_as, db):
    staff = login_as("calisan", name="Rol Değişecek")
    r = client.patch(f"/api/admin/users/{staff.user.id}", json={"name": "Rol Değişti", "role": "stajyer"})
    assert r.status_code == 200 and r.json()["role"] == "stajyer" and r.json()["name"] == "Rol Değişti"
    assert db.query(ActivityLog).filter_by(action="role_change").count() == 1
    bid = _analyzed_business(client, db, name="Rol Testi")
    assert staff.get(f"/api/businesses/{bid}/sales-note").status_code == 403, "yeni rolün yetkileri hemen uygulanır (stajyer satış notu oluşturamaz)"


def test_cannot_deactivate_or_demote_self_or_last_admin(client, admin_user, login_as):
    assert client.patch(f"/api/admin/users/{admin_user.id}", json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/admin/users/{admin_user.id}", json={"role": "calisan"}).status_code == 400
    second = login_as("yonetici")
    assert client.patch(f"/api/admin/users/{second.user.id}", json={"role": "calisan"}).status_code == 200  # bir yönetici daha var
    assert second.get("/api/admin/users").status_code == 403  # rolü düşürüldü → yetki hemen gitti


def test_admin_password_reset_forces_change_and_revokes_sessions(client, login_as):
    staff = login_as("calisan")
    r = client.post(f"/api/admin/users/{staff.user.id}/reset-password", json={"new_password": "Sifirla12345"})
    assert r.status_code == 200 and r.json()["temporary_password"] == "Sifirla12345"
    assert staff.get("/api/auth/me").status_code == 401, "sıfırlanınca eski oturumlar kapanır"
    fresh = TestClient(staff.app, headers=CSRF_HEADERS)
    assert fresh.post("/api/auth/login", json={"identifier": staff.user.email, "password": TEST_PASSWORD}).status_code == 401, "eski şifre geçersiz"
    assert fresh.post("/api/auth/login", json={"identifier": staff.user.email, "password": "Sifirla12345"}).status_code == 200
    assert fresh.get("/api/auth/me").json()["must_change_password"] is True


def test_user_changes_own_password(login_as):
    c = login_as("calisan")
    assert c.post("/api/auth/change-password", json={"current_password": "yanlis", "new_password": "YeniSifre123"}).status_code == 400
    assert c.post("/api/auth/change-password", json={"current_password": TEST_PASSWORD, "new_password": "zayif"}).status_code == 422
    assert c.post("/api/auth/change-password", json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD}).status_code == 422
    assert c.post("/api/auth/change-password", json={"current_password": TEST_PASSWORD, "new_password": "YeniSifre123"}).status_code == 200
    fresh = TestClient(c.app, headers=CSRF_HEADERS)
    assert fresh.post("/api/auth/login", json={"identifier": c.user.email, "password": "YeniSifre123"}).status_code == 200


# ================================================================ AKTİVİTE GEÇMİŞİ
def test_activity_log_records_who_did_what(client, login_as, db):
    staff = login_as("calisan", name="Ahmet Yılmaz")
    bid = _analyzed_business(client, db, name="ABC Diş Kliniği")
    staff.post(f"/api/businesses/{bid}/crm", json={"stage": "Arandı", "note": "ilk görüşme"})
    staff.patch(f"/api/businesses/{bid}/crm", json={"stage": "Teklif Gönderildi"})
    staff.patch(f"/api/businesses/{bid}/crm", json={"staff_note": "Fiyat gönderildi"})
    staff.get(f"/api/businesses/{bid}/sales-note")
    staff.post("/api/businesses/export", json={"ids": [bid], "format": "csv"})
    staff.post(f"/api/businesses/{bid}/analyze")
    staff.post("/api/discovery/jobs", json={"region_id": 1, "sector_id": 1, "target_count": 1, "auto_analyze": False})
    staff.patch(f"/api/businesses/{bid}/crm", json={"stage": "Kazanıldı"})
    staff.post("/api/auth/logout")
    log = client.get("/api/admin/activity", params={"user_id": staff.user.id, "limit": 200}).json()
    actions = {i["action"] for i in log["items"]}
    assert {"login", "crm_add", "crm_status", "crm_note", "offer", "customer_won", "sales_note", "export", "analyze", "search", "logout"} <= actions
    status = next(i for i in log["items"] if i["action"] == "crm_status" and (i["detail"] or "").endswith("Arandı → Teklif Gönderildi"))
    assert status["user_name"] == "Ahmet Yılmaz" and status["business_name"] == "ABC Diş Kliniği" and status["detail"].endswith("Arandı → Teklif Gönderildi")
    assert status["created_at"] and status["action_label"] == "CRM durumunu değiştirdi"
    filtered = client.get("/api/admin/activity", params={"action": "offer"}).json()
    assert filtered["total"] == 1 and filtered["items"][0]["business_id"] == bid


def test_failed_login_and_admin_actions_are_logged(anon_client, client, admin_user, db):
    anon_client.post("/api/auth/login", json={"identifier": "yonetici", "password": "Yanlis12345"})
    client.post("/api/admin/users", json={"name": "Yeni", "email": "yeni@example.test", "username": "yeni1", "role": "stajyer", "password": "Gecici12345"})
    actions = [a.action for a in db.query(ActivityLog).all()]
    assert "login_failed" in actions and "user_create" in actions


# ================================================================ CRM ↔ KULLANICI
def test_crm_records_first_adder_last_actor_and_history_users(client, login_as, db):
    ahmet, ayse = login_as("calisan", name="Ahmet Yılmaz"), login_as("stajyer", name="Ayşe Kaya")
    bid = _analyzed_business(client, db, name="Ortak CRM Firması")
    ahmet.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak", "note": "ilk arama"})
    ayse.patch(f"/api/businesses/{bid}/crm", json={"stage": "Arandı"})
    d = client.get(f"/api/businesses/{bid}").json()
    b = d["business"]
    assert b["crm_added_by_name"] == "Ahmet Yılmaz" and b["crm_updated_by_name"] == "Ayşe Kaya" and b["crm_last_action"] == "Aranacak → Arandı"
    assert [(h["user_name"], h["to_stage"]) for h in d["crm_history"]] == [("Ayşe Kaya", "Arandı"), ("Ahmet Yılmaz", "Aranacak")]
    listed = next(x for x in client.get("/api/crm").json()["items"] if x["id"] == bid)
    assert listed["crm_added_by_name"] == "Ahmet Yılmaz" and listed["crm_updated_by_name"] == "Ayşe Kaya" and listed["crm_updated_at"]


def test_legacy_crm_records_without_user_show_unknown_not_invented(client, db):
    from datetime import datetime, timezone

    bid = _analyzed_business(client, db, name="Eski Kayıt")
    b = db.get(Business, bid)
    b.crm_added_at = b.crm_updated_at = datetime.now(timezone.utc)
    b.crm_stage = "Aranacak"
    db.add(CrmActivity(business_id=bid, type="added", to_stage="Aranacak", created_by="personel"))
    db.commit()
    d = client.get(f"/api/businesses/{bid}").json()
    assert d["business"]["crm_added_by_name"] == "Bilinmiyor (eski kayıt)" and d["crm_history"][0]["user_name"] == "Bilinmiyor (eski kayıt)"


# ================================================================ ANALİZ ↔ KULLANICI
def test_analysis_history_records_user_and_repeats_are_separate_runs(client, login_as, db):
    from services.worker.tasks.analysis import run_analysis_job

    bid = _analyzed_business(client, db, name="Tekrar Analiz")
    ahmet, mucahit = login_as("calisan", name="Ahmet"), login_as("calisan", name="Mücahit")
    for who in (ahmet, mucahit):
        job = who.post(f"/api/businesses/{bid}/analyze")
        assert job.status_code == 200
        run_analysis_job(db, job.json()["id"])
        db.expire_all()
    history = client.get(f"/api/businesses/{bid}").json()["analysis_history"]
    assert [h["user_name"] for h in history[:2]] == ["Mücahit", "Ahmet"], "her analiz ayrı satır: kim analiz etti"
    assert all(h["completed_at"] and h["status"] in ("completed", "partial") for h in history[:2])
    assert client.get("/api/reports/analysis").json()["today"]["analyses"] == 3, "ilk analiz + iki tekrar = 3 ayrı analiz işlemi"
    assert client.get(f"/api/businesses/{bid}").json()["business"]["last_analyzed_by_name"] == "Mücahit"


def test_maintenance_reanalysis_is_not_counted_as_staff_analysis(client, db):
    from services.worker.tasks.analysis import run_analysis_job

    bid = _analyzed_business(client, db, name="Bakım Firması")
    before = client.get("/api/reports/analysis").json()["today"]["analyses"]
    job = AnalysisJob(business_id=bid, trigger="maintenance")
    db.add(job)
    db.commit()
    run_analysis_job(db, job.id)
    assert client.get("/api/reports/analysis").json()["today"]["analyses"] == before, "bakım yeniden hesaplaması personel sayacına girmez"
    assert client.get(f"/api/businesses/{bid}").json()["analysis_history"][0]["user_name"] == "Bakım (otomatik)"


def test_discovery_job_and_its_analyses_are_linked_to_the_searching_user(client, login_as, db, monkeypatch):
    from packages.db.models import DiscoveryJob
    from services.worker import tasks
    from services.worker.tasks import discovery as discovery_tasks

    queued = []
    monkeypatch.setattr(discovery_tasks.run_analysis_job_task, "delay", lambda job_id, *a: queued.append(job_id))
    staff = login_as("stajyer", name="Ayşe Kaya")
    r = staff.post("/api/discovery/jobs", json={"region_id": 1, "sector_id": 1, "target_count": 2, "auto_analyze": False})
    assert r.status_code == 200 and db.get(DiscoveryJob, r.json()["id"]).user_id == staff.user.id
    bid = _analyzed_business(client, db, name="Arama Sonucu")
    db.get(Business, bid).status = "discovered"
    db.commit()
    (job_id,) = discovery_tasks.queue_analysis(db, [bid], staff.user.id)
    assert db.get(AnalysisJob, job_id).user_id == staff.user.id and queued == [job_id], "aramadan otomatik başlayan analiz, aramayı yapan kullanıcıya bağlanır"


def test_analysis_state_labels(client, db):
    bid = _analyzed_business(client, db, name="Durum Etiketi")
    b = next(x for x in client.get("/api/businesses").json() if x["id"] == bid)
    assert b["analysis_state"] in ("completed", "partial") and b["analysis_state_label"] in ("Analiz tamamlandı", "Kısmen analiz edildi")
    business = db.get(Business, bid)
    business.status = "analyzing"
    db.commit()
    assert next(x for x in client.get("/api/businesses").json() if x["id"] == bid)["analysis_state_label"] == "Analiz ediliyor"
    business.status = "analysis_failed"
    db.commit()
    assert next(x for x in client.get("/api/businesses").json() if x["id"] == bid)["analysis_state_label"] == "Analiz başarısız"


# ================================================================ PERSONEL RAPORLARI
def test_staff_report_counts_per_user_from_real_records(client, login_as, db):
    from services.worker.tasks.analysis import run_analysis_job

    ahmet, ayse = login_as("calisan", name="Ahmet"), login_as("calisan", name="Ayşe")
    b1, b2 = _analyzed_business(client, db, name="Rapor Firma 1"), _analyzed_business(client, db, name="Rapor Firma 2")
    for who, bid in ((ahmet, b1), (ahmet, b2), (ayse, b1)):
        job = who.post(f"/api/businesses/{bid}/analyze").json()
        run_analysis_job(db, job["id"])
        db.expire_all()
    ahmet.post(f"/api/businesses/{b1}/crm", json={"stage": "Arandı"})
    ahmet.patch(f"/api/businesses/{b1}/crm", json={"stage": "Teklif Gönderildi"})
    ayse.post(f"/api/businesses/{b2}/crm", json={"stage": "Aranacak"})
    ayse.patch(f"/api/businesses/{b2}/crm", json={"stage": "Arandı"})
    rows = {r["name"]: r for r in client.get("/api/admin/reports/staff?period=today").json()["items"]}
    assert rows["Ahmet"]["analyses"] == 2 and rows["Ayşe"]["analyses"] == 1
    assert rows["Ahmet"]["calls"] == 1 and rows["Ahmet"]["offers"] == 1 and rows["Ayşe"]["calls"] == 1 and rows["Ayşe"]["offers"] == 0
    assert rows["Ahmet"]["crm_added"] == 1 and rows["Ayşe"]["crm_added"] == 1
    assert client.get("/api/admin/reports/staff?period=yil").status_code == 422
