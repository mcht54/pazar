"""CRM (üyelik, durum, not, işlem geçmişi, liste/filtre/sıralama/özet) ve analiz raporu (bugün/hafta/ay sayaçları, analiz zaman damgası)."""

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from packages.crm import CRM_STAGES, WORK_ORDER
from sqlalchemy import text

from packages.db.models import AnalysisJob, Business, Region, Sector
from services.reporting.analysis_stats import analysis_report, analyzed_business_ids, period_bounds, period_starts
from services.worker.tasks.analysis import run_analysis_job

from tests.conftest import make_user
from tests.test_sales_features import _analyzed_business

IST = ZoneInfo("Europe/Istanbul")


def _reanalyze(db, business_id) -> AnalysisJob:
    job = AnalysisJob(business_id=business_id)
    db.add(job)
    db.commit()
    run_analysis_job(db, job.id)
    db.expire_all()
    return db.get(AnalysisJob, job.id)


def _crm_ids(client, **params):
    return [b["id"] for b in client.get("/api/crm", params=params).json()["items"]]


# ================================================================ CRM ÜYELİĞİ: analiz ≠ CRM
def test_analysis_never_adds_a_business_to_crm(client, db):
    bid = _analyzed_business(client, db, name="Sadece Analiz Edilen")
    d = client.get(f"/api/businesses/{bid}").json()
    assert d["business"]["in_crm"] is False and d["business"]["crm_added_at"] is None and d["crm_history"] == []
    crm = client.get("/api/crm").json()
    assert crm["total"] == 0 and crm["items"] == [], "analiz edilen firma CRM'e otomatik düşmemeli"
    assert client.get("/api/crm/summary").json()["total"] == 0


def test_discovered_but_not_analyzed_business_is_not_counted_as_analyzed(client, db):
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    b = Business(name="Sadece Bulunan", sector_id=sector.id, region_id=region.id, google_place_id="gmaps_only_found", discovery_source="google_maps", status="discovered")
    db.add(b)
    db.commit()
    out = next(x for x in client.get("/api/businesses").json() if x["id"] == b.id)
    assert out["last_analysis_at"] is None and out["previously_analyzed"] is False, "keşif, analiz sayılmamalı"
    assert analyzed_business_ids(db, "total")[0] == []
    assert analysis_report(db)["total"]["analyses"] == 0


# ================================================================ CRM'E EKLEME + GEÇMİŞ
def test_add_to_crm_with_stage_and_note_creates_history_and_timestamps(client, db):
    bid = _analyzed_business(client, db)
    r = client.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak", "note": "İlk arama yapılacak."})
    assert r.status_code == 200
    body = r.json()
    assert body["in_crm"] is True and body["crm_stage"] == "Aranacak" and body["staff_note"] == "İlk arama yapılacak."
    assert body["crm_added_at"] and body["crm_updated_at"]
    assert [(h["type"], h["from_stage"], h["to_stage"], h["note"]) for h in body["history"]] == [("added", None, "Aranacak", "İlk arama yapılacak.")]
    assert client.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak"}).status_code == 409, "zaten CRM'deki firma tekrar eklenemez"
    assert client.post(f"/api/businesses/{bid}/crm", json={"stage": "Uydurma"}).status_code in (409, 422)
    assert client.post("/api/businesses/999999/crm", json={"stage": "Aranacak"}).status_code == 404
    assert bid in _crm_ids(client)


def test_add_to_crm_rejects_invalid_stage_for_new_member(client, db):
    bid = _analyzed_business(client, db)
    assert client.post(f"/api/businesses/{bid}/crm", json={"stage": "Uydurma"}).status_code == 422
    assert client.get(f"/api/businesses/{bid}").json()["business"]["in_crm"] is False


def test_stage_change_with_note_is_a_single_history_entry_and_updates_last_action(client, db):
    bid = _analyzed_business(client, db)
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak"})
    first = client.get(f"/api/businesses/{bid}").json()["business"]["crm_updated_at"]
    time.sleep(0.01)
    r = client.patch(f"/api/businesses/{bid}/crm", json={"stage": "Teklif Gönderildi", "staff_note": "Web sitesi + SEO fiyatı gönderildi."}).json()
    assert r["crm_stage"] == "Teklif Gönderildi" and r["crm_updated_at"] > first
    top = r["history"][0]
    assert (top["type"], top["from_stage"], top["to_stage"], top["note"]) == ("status_change", "Aranacak", "Teklif Gönderildi", "Web sitesi + SEO fiyatı gönderildi.")
    assert [h["type"] for h in r["history"]] == ["status_change", "added"], "en yeni kayıt en üstte"


def test_editing_only_the_note_logs_entry_with_current_stage_and_updates_last_action(client, db):
    bid = _analyzed_business(client, db)
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Takip Bekliyor", "note": "eski not"})
    before = client.get(f"/api/businesses/{bid}").json()["business"]["crm_updated_at"]
    time.sleep(0.01)
    r = client.patch(f"/api/businesses/{bid}/crm", json={"staff_note": "Pazartesi tekrar aranacak."}).json()
    assert r["crm_stage"] == "Takip Bekliyor" and r["staff_note"] == "Pazartesi tekrar aranacak." and r["crm_updated_at"] > before
    top = r["history"][0]
    assert (top["type"], top["to_stage"], top["note"]) == ("note", "Takip Bekliyor", "Pazartesi tekrar aranacak.")


def test_noop_update_does_not_touch_timestamp_or_history(client, db):
    bid = _analyzed_business(client, db)
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Arandı", "note": "not"})
    a = client.get(f"/api/businesses/{bid}").json()
    r = client.patch(f"/api/businesses/{bid}/crm", json={"stage": "Arandı", "staff_note": "not"}).json()
    assert r["crm_updated_at"] == a["business"]["crm_updated_at"] and len(r["history"]) == len(a["crm_history"]) == 1


def test_history_is_append_only_and_lists_every_stage_in_order(client, db):
    bid = _analyzed_business(client, db)
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak", "note": "İlk arama yapılacak."})
    client.patch(f"/api/businesses/{bid}/crm", json={"stage": "Arandı", "staff_note": "Firma sahibi ile görüşüldü."})
    client.patch(f"/api/businesses/{bid}/crm", json={"stage": "Teklif Gönderildi", "staff_note": "Fiyat gönderildi."})
    hist = client.get(f"/api/businesses/{bid}").json()["crm_history"]
    assert [h["to_stage"] for h in hist] == ["Teklif Gönderildi", "Arandı", "Aranacak"]
    assert [h["note"] for h in hist] == ["Fiyat gönderildi.", "Firma sahibi ile görüşüldü.", "İlk arama yapılacak."]
    times = [h["created_at"] for h in hist]
    assert times == sorted(times, reverse=True) and all(t for t in times)


# ================================================================ TEKRAR ANALİZ CRM'İ SİLMEZ
def test_reanalysis_keeps_crm_record_history_and_note(client, db):
    bid = _analyzed_business(client, db)
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Aranacak", "note": "İlk arama"})
    client.patch(f"/api/businesses/{bid}/crm", json={"stage": "Arandı", "staff_note": "Görüşüldü, teklif istiyor"})
    before = client.get(f"/api/businesses/{bid}").json()
    _reanalyze(db, bid)
    after = client.get(f"/api/businesses/{bid}").json()
    b0, b1 = before["business"], after["business"]
    assert b1["in_crm"] and b1["crm_stage"] == "Arandı" and b1["staff_note"] == "Görüşüldü, teklif istiyor"
    assert b1["crm_added_at"] == b0["crm_added_at"] and b1["crm_updated_at"] == b0["crm_updated_at"]
    assert after["crm_history"] == before["crm_history"], "yeniden analiz CRM geçmişine dokunmamalı"
    assert b1["last_analysis_at"] > b0["last_analysis_at"], "yeni analiz tamamlanınca zaman damgası güncellenmeli"
    assert bid in _crm_ids(client)


# ================================================================ ANALİZ ZAMAN DAMGASI + SAYAÇ
def test_analysis_timestamp_is_the_real_completion_time_and_matches_history(client, db):
    t0 = datetime.now(timezone.utc)
    bid = _analyzed_business(client, db)
    t1 = datetime.now(timezone.utc)
    business = db.get(Business, bid)
    job = db.query(AnalysisJob).filter_by(business_id=bid).one()
    assert business.last_analysis_at == job.completed_at, "firmanın son analiz tarihi = analiz geçmişindeki tamamlanma zamanı"
    assert t0 <= business.last_analysis_at <= t1
    assert job.status in ("completed", "partial")


def test_each_completed_analysis_is_counted_including_repeats_of_the_same_business(client, db):
    before = client.get("/api/reports/analysis").json()
    bid = _analyzed_business(client, db)
    mid = client.get("/api/reports/analysis").json()
    assert mid["today"]["analyses"] == before["today"]["analyses"] + 1
    assert mid["week"]["analyses"] == before["week"]["analyses"] + 1 and mid["month"]["analyses"] == before["month"]["analyses"] + 1 and mid["total"]["analyses"] == before["total"]["analyses"] + 1
    first = db.get(Business, bid).last_analysis_at
    _reanalyze(db, bid)
    after = client.get("/api/reports/analysis").json()
    assert after["today"]["analyses"] == before["today"]["analyses"] + 2, "aynı firmanın tekrar analizi ayrı bir işlem olarak sayılmalı"
    assert after["today"]["businesses"] == before["today"]["businesses"] + 1, "ama tekil firma sayısı 1 artar"
    assert db.get(Business, bid).last_analysis_at > first


def test_failed_analysis_is_not_counted_and_keeps_previous_timestamp(client, db, monkeypatch):
    bid = _analyzed_business(client, db)
    stamp = db.get(Business, bid).last_analysis_at
    counted = client.get("/api/reports/analysis").json()["today"]["analyses"]

    def boom(*args, **kwargs):
        raise RuntimeError("test amaçlı analiz hatası")

    monkeypatch.setattr("services.worker.tasks.analysis.build_competitor_snapshots", boom)
    job = AnalysisJob(business_id=bid)
    db.add(job)
    db.commit()
    with pytest.raises(RuntimeError):
        run_analysis_job(db, job.id)
    db.expire_all()
    assert db.get(AnalysisJob, job.id).status == "failed"
    assert client.get("/api/reports/analysis").json()["today"]["analyses"] == counted, "başarısız analiz sayıya dahil edilmemeli"
    assert db.get(Business, bid).last_analysis_at == stamp, "başarısız analiz son analiz tarihini değiştirmemeli"


def _make_business(db, name):
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    b = Business(name=name, sector_id=sector.id, region_id=region.id, google_place_id=f"gmaps_{name}", discovery_source="google_maps", status="analyzed")
    db.add(b)
    db.commit()
    return b


def test_period_bounds_are_half_open_istanbul_windows():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)  # Çarşamba 15:00 İstanbul
    b = period_bounds(now)
    assert b["today"] == (datetime(2026, 9, 23, 0, 0, tzinfo=IST), datetime(2026, 9, 24, 0, 0, tzinfo=IST)), "bugün: bugün 00:00 → yarın 00:00"
    assert b["today"][0].astimezone(timezone.utc) == datetime(2026, 9, 22, 21, 0, tzinfo=timezone.utc)
    assert b["week"] == (datetime(2026, 9, 21, 0, 0, tzinfo=IST), datetime(2026, 9, 28, 0, 0, tzinfo=IST)) and b["week"][0].weekday() == 0, "hafta: Pazartesi 00:00 → gelecek Pazartesi 00:00"
    assert b["month"] == (datetime(2026, 9, 1, 0, 0, tzinfo=IST), datetime(2026, 10, 1, 0, 0, tzinfo=IST)) and b["total"] == (None, None)
    # UTC'de hâlâ 'dün' olan an, İstanbul'da 'bugün' başlamış olabilir (gece 00:00 civarında yanlış güne geçme olmamalı)
    late = datetime(2026, 9, 23, 22, 30, tzinfo=timezone.utc)  # 24 Eylül 01:30 İstanbul
    assert period_bounds(late)["today"][0] == datetime(2026, 9, 24, 0, 0, tzinfo=IST)
    just_before = datetime(2026, 9, 23, 20, 59, 59, tzinfo=timezone.utc)  # 23 Eylül 23:59:59 İstanbul
    assert period_bounds(just_before)["today"][0] == datetime(2026, 9, 23, 0, 0, tzinfo=IST)
    # Pazar günü hâlâ aynı haftanın Pazartesi'ne bakar; Pazartesi 00:00'da yeni hafta başlar
    assert period_bounds(datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc))["week"][0] == datetime(2026, 9, 21, 0, 0, tzinfo=IST)
    assert period_bounds(datetime(2026, 9, 27, 21, 5, tzinfo=timezone.utc))["week"][0] == datetime(2026, 9, 28, 0, 0, tzinfo=IST)
    # yıl sonu: ay penceresi bir sonraki yılın Ocak'ına uzanır
    assert period_bounds(datetime(2026, 12, 15, 12, 0, tzinfo=timezone.utc))["month"][1] == datetime(2027, 1, 1, 0, 0, tzinfo=IST)
    assert period_starts(now)["today"] == datetime(2026, 9, 23, 0, 0, tzinfo=IST)


def test_counters_count_only_successfully_completed_runs_inside_each_half_open_istanbul_window(client, db):
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    a, b, c, d, e, f, g, h, i, j, k = (_make_business(db, n) for n in "abcdefghijk")
    U = lambda *args: datetime(*args, tzinfo=timezone.utc)
    runs = [
        (a, "completed", U(2026, 9, 23, 8, 0)),    # bugün
        (a, "completed", U(2026, 9, 23, 10, 0)),   # bugün — AYNI firma ikinci kez: ayrı analiz, tek firma
        (b, "partial", U(2026, 9, 23, 9, 0)),      # kısmen tamamlanan: SAYILMAZ (yalnızca başarıyla tamamlananlar)
        (c, "failed", U(2026, 9, 23, 9, 30)),      # başarısız: sayılmaz
        (d, "completed", U(2026, 9, 22, 20, 59)),  # 22 Eylül 23:59 İstanbul → dün (hafta+ay+toplam)
        (e, "completed", U(2026, 9, 22, 21, 0)),   # 23 Eylül 00:00:00 İstanbul → başlangıç DAHİL: bugün
        (f, "completed", U(2026, 9, 20, 20, 59)),  # 20 Eylül 23:59 (Pazar) → önceki hafta, bu ay
        (g, "completed", U(2026, 8, 31, 20, 59)),  # 31 Ağustos 23:59 → önceki ay: yalnızca toplam
        (h, "completed", U(2026, 9, 23, 21, 0)),   # 24 Eylül 00:00:00 İstanbul → bitiş HARİÇ: bugün DEĞİL; hafta/ay/toplam
        (i, "completed", U(2026, 9, 27, 21, 0)),   # 28 Eylül 00:00 (gelecek Pazartesi) → bu hafta DEĞİL; ay/toplam
        (j, "completed", U(2026, 9, 30, 21, 0)),   # 1 Ekim 00:00 → bu ay DEĞİL; yalnızca toplam
        (k, "running", None),                      # devam eden: sayılmaz
    ]
    for biz, status, when in runs:
        db.add(AnalysisJob(business_id=biz.id, status=status, completed_at=when))
    db.commit()
    r = analysis_report(db, now)
    assert r["timezone"] == "Europe/Istanbul" and r["updated_at"].startswith("2026-09-23T15:00:00+03:00")
    assert (r["today"]["analyses"], r["today"]["businesses"]) == (3, 2)   # a,a,e → 2 benzersiz firma
    assert (r["week"]["analyses"], r["week"]["businesses"]) == (5, 4)     # + d, h
    assert (r["month"]["analyses"], r["month"]["businesses"]) == (7, 6)   # + f, i
    assert (r["total"]["analyses"], r["total"]["businesses"]) == (9, 8)   # + g, j
    assert r["first_analysis_at"].startswith("2026-08-31T23:59"), "ilk başarılı analiz kaydı (İstanbul)"
    ids, n = analyzed_business_ids(db, "today", now)
    assert n == 3 and set(ids) == {a.id, e.id} and ids[0] == a.id, "en son analiz edilen başta (a: 10:00 UTC)"
    assert analyzed_business_ids(db, "week", now)[1] == 5 and analyzed_business_ids(db, "total", now)[1] == 9


def test_same_business_analyzed_five_times_is_five_analyses_one_business(client, db):
    biz = _make_business(db, "tekrarli")
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    for hour in (5, 6, 7, 8, 9):
        db.add(AnalysisJob(business_id=biz.id, status="completed", completed_at=datetime(2026, 9, 23, hour, 0, tzinfo=timezone.utc)))
    db.commit()
    r = analysis_report(db, now)
    for key in ("today", "week", "month", "total"):
        assert (r[key]["analyses"], r[key]["businesses"]) == (5, 1), key


def test_discovery_and_maintenance_are_never_counted_as_analysis(client, db):
    from packages.db.models import DiscoveryJob

    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    db.add(DiscoveryJob(region_id=region.id, sector_id=sector.id, target_count=5, status="completed", found_new=5))
    biz = _make_business(db, "sadece-kesif")
    db.add(AnalysisJob(business_id=biz.id, status="completed", trigger="maintenance", completed_at=datetime.now(timezone.utc)))
    db.commit()
    r = analysis_report(db)
    assert r["total"]["analyses"] == 0 and r["total"]["businesses"] == 0 and r["first_analysis_at"] is None


def test_legacy_bulk_maintenance_migration_reclassifies_only_bursts_and_is_reversible(seeded_db):
    """f1cd02430a13: toplu (dakikada ≥20, ≥5 kayıt) ve kullanıcısız eski yeniden hesaplamalar 'maintenance' olur; gerçek/yavaş analizler dokunulmaz."""
    import importlib.util
    from pathlib import Path

    db = seeded_db
    path = next(Path(__file__).resolve().parent.parent.glob("packages/db/migrations/versions/*reclassify_legacy_bulk_maintenance_runs.py"))
    spec = importlib.util.spec_from_file_location("reclassify_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    businesses = [_make_business(db, f"m{n}") for n in range(20)]
    base = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    rows = {}
    for n in range(8):  # toplu: 8 kayıt, 1 sn arayla, kullanıcısız → yeniden sınıflandırılmalı
        rows[f"bulk{n}"] = AnalysisJob(business_id=businesses[n].id, status="completed", completed_at=base + timedelta(seconds=n))
    for n in range(5):  # gerçek: araştırma yapan analizler ~40 sn aralıklı → dokunulmamalı
        rows[f"slow{n}"] = AnalysisJob(business_id=businesses[8 + n].id, status="completed", completed_at=base + timedelta(hours=3, seconds=40 * n))
    for n in range(8):  # toplu görünümlü ama KULLANICILI → dokunulmamalı
        rows[f"user{n}"] = AnalysisJob(business_id=businesses[13 + n % 6].id, status="completed", completed_at=base + timedelta(hours=6, seconds=n), user_id=None)
    admin = make_user(db, "yonetici", email="mig@example.test", username="mig")
    for n in range(8):
        rows[f"user{n}"].user_id = admin.id
    for job in rows.values():
        db.add(job)
    db.commit()
    db.execute(text(module.RECLASSIFY_SQL))
    db.commit()
    db.expire_all()
    triggers = {k: db.get(AnalysisJob, v.id).trigger for k, v in rows.items()}
    assert all(triggers[f"bulk{n}"] == "maintenance" for n in range(8))
    assert all(triggers[f"slow{n}"] == "user" for n in range(5)) and all(triggers[f"user{n}"] == "user" for n in range(8))
    assert db.get(AnalysisJob, rows["bulk0"].id).stages_status.get("legacy_reclassified") is True and rows["bulk0"].completed_at is not None
    assert db.query(AnalysisJob).count() == len(rows), "hiçbir kayıt silinmedi"
    db.execute(text(module.REVERT_SQL))
    db.commit()
    db.expire_all()
    assert all(db.get(AnalysisJob, rows[f"bulk{n}"].id).trigger == "user" and "legacy_reclassified" not in db.get(AnalysisJob, rows[f"bulk{n}"].id).stages_status for n in range(8)), "downgrade birebir geri alır"


def test_report_endpoints_return_real_counts_and_businesses(client, db):
    b1 = _analyzed_business(client, db, name="Bugün Analiz A")
    b2 = _analyzed_business(client, db, name="Bugün Analiz B")
    rep = client.get("/api/reports/analysis").json()
    assert rep["today"]["analyses"] == 2 and rep["today"]["businesses"] == 2 and rep["total"]["analyses"] == 2
    assert rep["today"]["since"] and set(rep) >= {"today", "week", "month", "total", "timezone", "updated_at", "first_analysis_at"}
    today = client.get("/api/reports/analysis/businesses?period=today").json()
    assert today["label"] == "Bugün" and today["analyses"] == 2 and {x["id"] for x in today["items"]} == {b1, b2}
    assert all(x["last_analysis_at"] and x["sales_score"] is not None for x in today["items"])
    assert client.get("/api/reports/analysis/businesses?period=month").json()["businesses_count"] == 2
    assert client.get("/api/reports/analysis/businesses?period=yil").status_code == 422


# ================================================================ CRM LİSTESİ / FİLTRE / SIRALAMA / ÖZET
def _seed_crm(client, db):
    a = _analyzed_business(client, db, name="Aranacak Klinik", phone="0532 111 00 01")
    b = _analyzed_business(client, db, name="Teklifli Merkez", phone="0532 222 00 02")
    c = _analyzed_business(client, db, name="Görüşülen İşitme", phone="0532 333 00 03", sector_name="Diş Kliniği")
    _analyzed_business(client, db, name="CRM Dışı Firma")
    client.post(f"/api/businesses/{a}/crm", json={"stage": "Aranacak", "note": "ilk arama"})
    time.sleep(0.01)
    client.post(f"/api/businesses/{b}/crm", json={"stage": "Teklif Gönderildi", "note": "fiyat gitti"})
    time.sleep(0.01)
    client.post(f"/api/businesses/{c}/crm", json={"stage": "Görüşüldü"})
    return a, b, c


def test_crm_list_contains_only_crm_members_with_required_fields(client, db):
    a, b, c = _seed_crm(client, db)
    data = client.get("/api/crm").json()
    assert data["total"] == 3 and data["filtered_total"] == 3 and {x["id"] for x in data["items"]} == {a, b, c}
    item = next(x for x in data["items"] if x["id"] == a)
    for key in ("name", "sector_name", "province_name", "district_name", "phone", "crm_stage", "last_analysis_at", "crm_updated_at", "sales_score",
                "primary_service", "sales_note", "staff_note", "maps_search_url", "verification"):
        assert key in item, key
    assert item["province_name"] == "Sakarya" and item["district_name"] == "Serdivan" and item["sector_name"] == "İşitme Cihazı Merkezi"
    assert item["crm_stage"] == "Aranacak" and item["staff_note"] == "ilk arama" and item["sales_score"] is not None
    assert data["counts"]["Aranacak"] == 1 and data["counts"]["Teklif Gönderildi"] == 1 and data["counts"]["Görüşüldü"] == 1 and data["counts"]["Kazanıldı"] == 0
    assert set(data["counts"]) == set(CRM_STAGES)


def test_crm_filters_stage_search_region_sector_service_and_combination(client, db):
    a, b, c = _seed_crm(client, db)
    assert _crm_ids(client, stage="Aranacak") == [a]
    assert _crm_ids(client, stage="Kaybedildi") == []
    assert set(_crm_ids(client, q="klinik")) == {a}, "büyük/küçük harf ve Türkçe karakter duyarsız arama"
    assert set(_crm_ids(client, q="0532 222")) == {b} and set(_crm_ids(client, q="532222")) == {b}, "telefonla arama"
    assert set(_crm_ids(client, q="fiyat gitti")) == {b}, "CRM notunda arama"
    facets = client.get("/api/crm").json()["facets"]
    sakarya = next(p["id"] for p in facets["provinces"] if p["name"] == "Sakarya")
    serdivan = next(d["id"] for d in facets["districts"] if d["name"] == "Serdivan")
    diş = next(s["id"] for s in facets["sectors"] if s["name"] == "Diş Kliniği")
    assert set(_crm_ids(client, province_id=sakarya)) == {a, b, c} and set(_crm_ids(client, district_id=serdivan)) == {a, b, c}
    assert _crm_ids(client, sector_id=diş) == [c]
    # "Sakarya + sektör + Teklif Gönderildi" gibi birleşik filtre
    assert _crm_ids(client, province_id=sakarya, stage="Teklif Gönderildi") == [b]
    assert _crm_ids(client, province_id=sakarya, sector_id=diş, stage="Teklif Gönderildi") == []
    service = next(x["primary_service"] for x in client.get("/api/crm").json()["items"] if x["primary_service"])
    assert set(_crm_ids(client, service=service)) <= {a, b, c} and _crm_ids(client, service=service)
    assert client.get("/api/crm", params={"stage": "Uydurma"}).status_code == 422
    assert client.get("/api/crm", params={"sort": "uydurma"}).status_code == 422


def test_crm_sorting_options(client, db):
    a, b, c = _seed_crm(client, db)
    assert _crm_ids(client) == [c, b, a], "varsayılan: son işleme göre (en yeni önce)"
    assert _crm_ids(client, sort="stage") == [a, c, b], "durum: çalışma sırası (Aranacak → Daha Sonra Ara → Takip Bekliyor → …)"
    assert WORK_ORDER[0] == "Aranacak" and WORK_ORDER[1] == "Daha Sonra Ara"
    by_score = client.get("/api/crm", params={"sort": "score"}).json()["items"]
    scores = [x["sales_score"] for x in by_score]
    assert scores == sorted(scores, reverse=True)
    assert _crm_ids(client, sort="name") == sorted([a, b, c], key=lambda i: {a: "Aranacak Klinik", b: "Teklifli Merkez", c: "Görüşülen İşitme"}[i].lower())
    # güncelleme, son işlem sırasını değiştirir
    client.patch(f"/api/businesses/{a}/crm", json={"staff_note": "yeni not"})
    assert _crm_ids(client)[0] == a
    analyzed = client.get("/api/crm", params={"sort": "analyzed"}).json()["items"]
    stamps = [x["last_analysis_at"] for x in analyzed]
    assert stamps == sorted(stamps, reverse=True)


def test_crm_summary_counts_by_stage_from_real_records(client, db):
    a, b, c = _seed_crm(client, db)
    s = client.get("/api/crm/summary").json()
    assert s["total"] == 3 and s["by_stage"]["Aranacak"] == 1 and s["by_stage"]["Teklif Gönderildi"] == 1 and s["by_stage"]["Görüşüldü"] == 1
    client.patch(f"/api/businesses/{b}/crm", json={"stage": "Kazanıldı"})
    s2 = client.get("/api/crm/summary").json()
    assert s2["total"] == 3 and s2["by_stage"]["Kazanıldı"] == 1 and s2["by_stage"]["Teklif Gönderildi"] == 0


def test_export_marks_non_crm_businesses(client, db):
    import csv
    import io

    a, b, c = _seed_crm(client, db)
    outside = next(x["id"] for x in client.get("/api/businesses").json() if x["name"] == "CRM Dışı Firma")
    r = client.post("/api/businesses/export", json={"ids": [a, outside], "format": "csv"})
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    by_name = {x["İşletme adı"]: x for x in rows}
    assert by_name["Aranacak Klinik"]["CRM durumu"] == "Aranacak" and by_name["CRM Dışı Firma"]["CRM durumu"] == "CRM'de değil"


def test_dashboard_still_offers_non_crm_businesses_and_callable_crm_ones(client, db):
    a, b, c = _seed_crm(client, db)
    outside = next(x["id"] for x in client.get("/api/businesses").json() if x["name"] == "CRM Dışı Firma")
    ids = {x["id"] for x in client.get("/api/dashboard/today?min_score=1&limit=50").json()}
    assert outside in ids and a in ids, "CRM'de olmayan (Yeni) ve 'Aranacak' firmalar panelde kalır"
    assert b not in ids and c not in ids, "Teklif Gönderildi / Görüşüldü artık 'bugün ara' listesinde olmamalı"
