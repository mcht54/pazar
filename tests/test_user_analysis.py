"""Kullanıcı bazlı analiz geçmişi: 'Daha önce analiz edildi' YALNIZCA bakan kullanıcının kendi başarılı analizi varsa görünür."""

from datetime import datetime, timezone

from sqlalchemy import text

from packages.db.models import AnalysisJob, Business, UserAnalysis
from services.worker.tasks.analysis import run_analysis_job

from tests.test_crm_and_reports import _make_business
from tests.test_sales_features import _analyzed_business


def _analyze_as(db, business_id, user_id):
    job = AnalysisJob(business_id=business_id, user_id=user_id)
    db.add(job)
    db.commit()
    run_analysis_job(db, job.id)
    db.expire_all()
    return db.get(AnalysisJob, job.id)


def _flags(client, bid):
    d = client.get(f"/api/businesses/{bid}").json()["business"]
    return d["previously_analyzed"], d["analyzed_by_me"], d["analyzed_by_others"]


def test_user_b_does_not_see_user_a_analysis_as_previous(client, login_as, db):
    a, b = login_as("calisan", name="Kullanıcı A"), login_as("calisan", name="Kullanıcı B")
    bid = _analyzed_business(client, db, name="İki Kullanıcılı Firma", user_id=a.user.id)
    assert _flags(a, bid) == (True, True, False), "A kendi analizini 'daha önce analiz edildi' olarak görür"
    listed_a = next(x for x in a.get("/api/businesses?region_id=%d" % db.get(Business, bid).region_id).json() if x["id"] == bid)
    assert listed_a["analyzed_by_me"] is True
    # B: işletme sistemde analiz edilmiş ama B kendisi analiz etmedi
    prev, mine, others = _flags(b, bid)
    assert (prev, mine, others) == (False, False, True), "B için 'daha önce analiz edildi' GÖSTERİLMEMELİ"
    listed_b = next(x for x in b.get("/api/businesses?region_id=%d" % db.get(Business, bid).region_id).json() if x["id"] == bid)
    assert listed_b["previously_analyzed"] is False and listed_b["analyzed_by_others"] is True
    # B analiz edilebilir: yeni analiz başlatır
    assert b.post(f"/api/businesses/{bid}/analyze").status_code in (200, 202)


def test_after_b_analyzes_both_have_their_own_record_and_runs_increase(client, login_as, db):
    a, b = login_as("calisan"), login_as("calisan")
    bid = _analyzed_business(client, db, name="Ortak Firma", user_id=a.user.id)
    _analyze_as(db, bid, b.user.id)
    assert _flags(b, bid)[1] is True and _flags(a, bid)[1] is True
    rows = {r.user_id: r for r in db.query(UserAnalysis).filter_by(business_id=bid).all()}
    assert set(rows) == {a.user.id, b.user.id} and rows[a.user.id].runs == 1 and rows[b.user.id].runs == 1
    _analyze_as(db, bid, a.user.id)
    db.expire_all()
    assert db.query(UserAnalysis).filter_by(business_id=bid, user_id=a.user.id).one().runs == 2, "aynı kullanıcının tekrarı aynı satırı günceller (unique)"
    assert db.query(UserAnalysis).filter_by(business_id=bid).count() == 2
    assert db.query(AnalysisJob).filter_by(business_id=bid, status="completed").count() == 3, "her analiz işlemi analysis_jobs'ta ayrı satır olarak kalır"
    assert db.query(UserAnalysis).filter_by(business_id=bid, user_id=b.user.id).one().runs == 1, "B'nin kaydına A'nın tekrarı dokunmaz"


def test_only_successful_user_analyses_count(client, login_as, db):
    a = login_as("calisan")
    bid = _analyzed_business(client, db, name="Sistem Analizli", user_id=None)  # kullanıcısı olmayan analiz
    assert _flags(a, bid) == (False, False, True) and db.query(UserAnalysis).count() == 0
    # başarısız / kısmi / bakım analizleri sayılmaz
    db.add(AnalysisJob(business_id=bid, user_id=a.user.id, status="failed", completed_at=datetime.now(timezone.utc)))
    db.add(AnalysisJob(business_id=bid, user_id=a.user.id, status="partial", completed_at=datetime.now(timezone.utc)))
    db.commit()
    assert db.query(UserAnalysis).count() == 0 and _flags(a, bid)[1] is False
    job = AnalysisJob(business_id=bid, user_id=a.user.id, trigger="maintenance")
    db.add(job)
    db.commit()
    run_analysis_job(db, job.id)
    db.expire_all()
    assert db.query(UserAnalysis).count() == 0, "bakım yeniden hesaplaması kullanıcı analizi sayılmaz"
    _analyze_as(db, bid, a.user.id)
    assert _flags(a, bid) == (True, True, False)


def test_discovered_but_never_analyzed_business_shows_no_analysis_flags(client, login_as, db):
    a = login_as("calisan")
    b = _make_business(db, "Sadece Keşfedildi")
    db.query(Business).filter_by(id=b.id).update({"status": "discovered"})
    db.commit()
    assert _flags(a, b.id) == (False, False, False), "sistemde bulunmak analiz edilmiş demek değildir"


def test_flags_in_crm_call_today_and_dashboard_are_per_viewer(client, login_as, db):
    a, b = login_as("calisan"), login_as("calisan")
    bid = _analyzed_business(client, db, name="Panel Firması", user_id=a.user.id)
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Yeni"})
    mine = next(i["business"] for i in a.get("/api/sales/call-today?limit=50&scope=all").json()["items"] if i["business"]["id"] == bid)
    theirs = next(i["business"] for i in b.get("/api/sales/call-today?limit=50&scope=all").json()["items"] if i["business"]["id"] == bid)
    assert mine["analyzed_by_me"] is True and theirs["analyzed_by_me"] is False and theirs["analyzed_by_others"] is True
    crm_a = next(x for x in a.get("/api/crm").json()["items"] if x["id"] == bid)
    crm_b = next(x for x in b.get("/api/crm").json()["items"] if x["id"] == bid)
    assert (crm_a["analyzed_by_me"], crm_b["analyzed_by_me"]) == (True, False)
    assert next(x for x in a.get("/api/dashboard/today?min_score=1").json() if x["id"] == bid)["analyzed_by_me"] is True
    assert next(x for x in b.get("/api/dashboard/today?min_score=1").json() if x["id"] == bid)["analyzed_by_me"] is False


def test_user_analyses_backfill_migration_uses_only_known_user_successful_runs(seeded_db):
    """c4d8e2f6a112 geri doldurma SQL'i: yalnızca kullanıcısı bilinen, tamamlanmış, bakım olmayan analizler; kullanıcısız eski analizler hiçbir kullanıcıya atfedilmez."""
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.conftest import make_user

    db = seeded_db
    u1, u2 = make_user(db, "calisan"), make_user(db, "calisan")
    biz = [_make_business(db, f"Geri Doldur {n}") for n in range(3)]
    now = datetime.now(timezone.utc)
    db.add_all([
        AnalysisJob(business_id=biz[0].id, user_id=u1.id, status="completed", completed_at=now),
        AnalysisJob(business_id=biz[0].id, user_id=u1.id, status="completed", completed_at=now),
        AnalysisJob(business_id=biz[0].id, user_id=u2.id, status="partial", completed_at=now),
        AnalysisJob(business_id=biz[1].id, user_id=None, status="completed", completed_at=now),
        AnalysisJob(business_id=biz[1].id, user_id=u2.id, status="completed", trigger="maintenance", completed_at=now),
        AnalysisJob(business_id=biz[2].id, user_id=u2.id, status="failed", completed_at=now),
    ])
    db.commit()
    path = next(Path(__file__).resolve().parent.parent.glob("packages/db/migrations/versions/*user_analyses_follow_ups_indexes.py"))
    spec = importlib.util.spec_from_file_location("user_analysis_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # tablo zaten var: yalnızca geri doldurma ifadesini çalıştır
    backfill = [s for s in module.upgrade.__code__.co_consts if isinstance(s, str) and "INSERT INTO user_analyses" in s][0]
    db.execute(text(backfill))
    db.commit()
    rows = db.query(UserAnalysis).all()
    assert [(r.user_id, r.business_id, r.runs) for r in rows] == [(u1.id, biz[0].id, 2)], "yalnızca u1'in iki başarılı analizi tek satırda toplanır"
