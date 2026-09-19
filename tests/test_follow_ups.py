"""Takip sistemi: oluştur · düzenle · iptal · tamamla · listele (Bugün / Gecikmiş / Yarın / Bu Hafta) · sayfalama · yetki · 'Bugün Kimi Arayalım' entegrasyonu."""

from datetime import datetime, timedelta, timezone

from packages.db.models import CrmActivity, FollowUp
from services import follow_up_service as fus
from services.crm_service import TZ

from tests.test_sales_features import _analyzed_business

NOW = lambda: datetime.now(timezone.utc)


def _day(offset: int) -> str:
    return (NOW().astimezone(TZ).date() + timedelta(days=offset)).isoformat()


def _create(client, bid, due, note=None, **extra):
    r = client.post("/api/follow-ups", json={"business_id": bid, "due_at": due, "note": note, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client, **params):
    r = client.get("/api/follow-ups", params={"scope": "all", "page_size": 100, **params})
    assert r.status_code == 200, r.text
    return [x["id"] for x in r.json()["items"]], r.json()


def test_create_follow_up_with_date_time_note_status_and_user(client, db):
    bid = _analyzed_business(client, db, name="Takip Firması")
    day_only = _create(client, bid, _day(1), "Fiyat sor")
    assert day_only["status"] == "Bekliyor" and day_only["has_time"] is False and day_only["note"] == "Fiyat sor"
    assert day_only["user_name"] == "Test Yönetici" and day_only["business"]["name"] == "Takip Firması" and day_only["date_state"] == "upcoming"
    timed = _create(client, bid, f"{_day(2)}T14:30:00+03:00", "Öğleden sonra ara")
    assert timed["has_time"] is True and timed["due_at"].startswith(_day(2)) and "T14:30" in timed["due_at"].replace("+03:00", "")
    detail = client.get(f"/api/businesses/{bid}").json()["business"]
    assert detail["in_crm"] and detail["crm_stage"] == "Yeni", "takip planlamak açık bir CRM işlemidir: firma Yeni olarak CRM'e alınır"
    assert detail["next_follow_up_at"].startswith(_day(1)), "önbellek en yakın bekleyen takibi gösterir"
    hist = client.get(f"/api/businesses/{bid}").json()["crm_history"]
    assert hist[0]["type"] == "follow_up" and hist[0]["note"] == "Takip planlandı" and hist[0]["meta"]["follow_up_id"] == timed["id"]
    assert client.post("/api/follow-ups", json={"business_id": bid, "due_at": "31.31.2026"}).status_code == 422
    assert client.post("/api/follow-ups", json={"business_id": bid, "due_at": ""}).status_code == 422
    assert client.post("/api/follow-ups", json={"business_id": 999999, "due_at": _day(1)}).status_code == 404


def test_ranges_today_overdue_tomorrow_week_upcoming_and_counts(client, db):
    ids = {}
    for name, off in (("dun", -2), ("bugun", 0), ("yarin", 1), ("hafta_sonu", 30), ("uzak", 40)):
        bid = _analyzed_business(client, db, name=f"Aralık {name}")
        ids[name] = _create(client, bid, _day(off))["id"]
    week_start, week_end = fus.week_bounds()
    in_week = {n for n, off in (("dun", -2), ("bugun", 0), ("yarin", 1), ("hafta_sonu", 30), ("uzak", 40))
               if week_start <= (NOW().astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=off)) < week_end}
    assert _ids(client, range="overdue")[0] == [ids["dun"]]
    assert _ids(client, range="today")[0] == [ids["bugun"]]
    assert _ids(client, range="tomorrow")[0] == [ids["yarin"]]
    assert set(_ids(client, range="week")[0]) == {ids[n] for n in in_week - {"dun"}}, "bu hafta: bugün → gelecek Pazartesi"
    assert set(_ids(client, range="upcoming")[0]) == {ids["yarin"], ids["hafta_sonu"], ids["uzak"]}
    assert set(_ids(client, range="all")[0]) == set(ids.values())
    counts = _ids(client, range="all")[1]["counts"]
    assert counts["overdue"] == 1 and counts["today"] == 1 and counts["tomorrow"] == 1 and counts["upcoming"] == 3
    assert _ids(client, range="overdue")[1]["items"][0]["date_state"] == "overdue"
    assert client.get("/api/follow-ups?range=dun").status_code == 422 and client.get("/api/follow-ups?status=x").status_code == 422
    dash = client.get("/api/crm/follow-ups?scope=all").json()
    assert dash["counts"]["overdue"] == 1 and dash["counts"]["today"] == 1 and dash["counts"]["tomorrow"] == 1 and "week" in dash and "tomorrow" in dash


def test_multiple_follow_ups_per_business_and_cache_follows_the_nearest(client, db):
    bid = _analyzed_business(client, db, name="Çok Takipli")
    late = _create(client, bid, _day(5), "ikinci")
    early = _create(client, bid, _day(1), "birinci")
    nxt = lambda: client.get(f"/api/businesses/{bid}").json()["business"]["next_follow_up_at"][:10]
    assert nxt() == _day(1)
    done = client.post(f"/api/follow-ups/{early['id']}/complete", json={"result": "Görüşüldü", "note": "konuşuldu"})
    assert done.status_code == 200 and done.json()["status"] == "Tamamlandı" and done.json()["result"] == "Görüşüldü"
    assert nxt() == _day(5), "en yakın takip tamamlanınca önbellek sonraki bekleyene geçer"
    state = client.get(f"/api/businesses/{bid}").json()
    assert [f["id"] for f in client.get("/api/crm/follow-ups?scope=all").json()["upcoming"] if f["id"] == bid] == [bid]
    fu = client.get(f"/api/follow-ups?scope=all&status=all&business_id={bid}&range=all").json()["items"]
    assert {(f["id"], f["status"]) for f in fu} == {(late["id"], "Bekliyor"), (early["id"], "Tamamlandı")}
    assert state["crm_history"][0]["type"] == "follow_up_done" and state["crm_history"][0]["meta"]["follow_up_id"] == early["id"]


def test_edit_cancel_and_complete_rules(client, login_as, db):
    staff, intern = login_as("calisan", name="Ayşe Çalışan"), login_as("stajyer", name="Can Stajyer")
    bid = _analyzed_business(client, db, name="Düzenlenen Takip")
    fu = _create(client, bid, _day(3), "ilk not")
    patched = client.patch(f"/api/follow-ups/{fu['id']}", json={"due_at": f"{_day(4)}T09:15:00+03:00", "note": "yeni not", "user_id": staff.user.id}).json()
    assert patched["due_at"].startswith(_day(4)) and patched["has_time"] and patched["note"] == "yeni not" and patched["user_name"] == "Ayşe Çalışan"
    assert client.get(f"/api/businesses/{bid}").json()["business"]["next_follow_up_at"].startswith(_day(4))
    assert client.patch(f"/api/follow-ups/{fu['id']}", json={"due_at": ""}).status_code == 422
    assert client.patch(f"/api/follow-ups/{fu['id']}", json={"status": "Tamamlandı"}).status_code == 422, "tamamlamak /complete ile yapılır"
    assert intern.patch(f"/api/follow-ups/{fu['id']}", json={"note": "x"}).status_code == 403, "stajyer başkasının takibini değiştiremez"
    assert intern.post(f"/api/follow-ups/{fu['id']}/complete", json={"result": "Görüşüldü"}).status_code == 403
    own = _create(intern, bid, _day(6), "stajyerin takibi")
    assert intern.patch(f"/api/follow-ups/{own['id']}", json={"note": "güncel"}).status_code == 200
    assert intern.patch(f"/api/follow-ups/{own['id']}", json={"user_id": staff.user.id}).status_code == 403, "başkasına atama yetkisi yok"
    cancelled = client.patch(f"/api/follow-ups/{fu['id']}", json={"status": "İptal"}).json()
    assert cancelled["status"] == "İptal" and cancelled["result"] == "İptal edildi"
    assert client.patch(f"/api/follow-ups/{fu['id']}", json={"note": "x"}).status_code == 409, "iptal edilen takip değiştirilemez"
    assert client.post(f"/api/follow-ups/{fu['id']}/complete", json={"result": "Görüşüldü"}).status_code == 409
    assert db.get(FollowUp, fu["id"]) is not None, "iptal silme değildir"
    done = client.post(f"/api/follow-ups/{own['id']}/complete", json={"result": "Tekrar takip edilecek", "next_follow_up_at": _day(9)}).json()
    assert done["status"] == "Tamamlandı"
    assert client.post(f"/api/follow-ups/{own['id']}/complete", json={"result": "Görüşüldü"}).status_code == 409, "aynı takip iki kez tamamlanamaz"
    assert client.post(f"/api/follow-ups/{own['id']}/complete", json={"result": "Bilinmeyen"}).status_code in (409, 422)
    assert client.get("/api/follow-ups?scope=all&range=all").json()["total"] == 1, "tamamlanınca yeni tarih için yeni bekleyen takip açıldı"
    assert client.patch("/api/follow-ups/999999", json={"note": "x"}).status_code == 404


def test_time_passed_today_is_still_today_not_overdue(client, db):
    bid = _analyzed_business(client, db, name="Saati Geçen")
    minute_ago = (NOW() - timedelta(minutes=1)).astimezone(TZ).isoformat(timespec="seconds")
    fu = _create(client, bid, minute_ago, "saati geçti")
    if NOW().astimezone(TZ).hour == 0 and NOW().astimezone(TZ).minute < 2:
        return  # gece yarısı sınırında gün değişebilir
    assert fu["has_time"] and fu["date_state"] == "today" and fu["time_passed"] is True
    assert _ids(client, range="today")[0] == [fu["id"]] and _ids(client, range="overdue")[0] == []


def test_closing_business_cancels_pending_follow_ups_but_keeps_them(client, db):
    bid = _analyzed_business(client, db, name="Kapanacak Firma")
    a, b = _create(client, bid, _day(2)), _create(client, bid, _day(4))
    client.patch(f"/api/businesses/{bid}/crm", json={"stage": "Kazanıldı", "sale_amount": 100})
    rows = {r.id: r for r in db.query(FollowUp).filter_by(business_id=bid).all()}
    assert {r.status for r in rows.values()} == {"İptal"} and all(r.result == "Firma kapandı" for r in rows.values()) and set(rows) == {a["id"], b["id"]}
    assert client.get(f"/api/businesses/{bid}").json()["business"]["next_follow_up_at"] is None
    assert client.post("/api/follow-ups", json={"business_id": bid, "due_at": _day(3)}).status_code == 422


def test_crm_form_follow_up_field_updates_the_follow_up_row(client, db):
    bid = _analyzed_business(client, db, name="Form Takibi")
    client.post(f"/api/businesses/{bid}/crm", json={"stage": "Yeni", "follow_up_at": _day(2), "follow_up_note": "form notu"})
    rows = db.query(FollowUp).filter_by(business_id=bid).all()
    assert len(rows) == 1 and rows[0].status == "Bekliyor" and rows[0].note == "form notu" and rows[0].user_id
    client.patch(f"/api/businesses/{bid}/crm", json={"follow_up_at": _day(5)})
    db.expire_all()
    rows = db.query(FollowUp).filter_by(business_id=bid).all()
    assert len(rows) == 1 and rows[0].due_at.astimezone(TZ).date().isoformat() == _day(5), "aynı bekleyen takip güncellenir (yeni satır açılmaz)"
    client.patch(f"/api/businesses/{bid}/crm", json={"follow_up_at": None})
    db.expire_all()
    assert [r.status for r in db.query(FollowUp).filter_by(business_id=bid).all()] == ["İptal"]
    assert client.get(f"/api/businesses/{bid}").json()["business"]["next_follow_up_at"] is None


def test_pagination_and_scope(client, login_as, db):
    staff = login_as("calisan")
    for n in range(7):
        bid = _analyzed_business(client, db, name=f"Sayfa {n}")
        _create(client, bid, _day(1 + n))
    p1 = client.get("/api/follow-ups?scope=all&range=all&page=1&page_size=3").json()
    p3 = client.get("/api/follow-ups?scope=all&range=all&page=3&page_size=3").json()
    assert p1["total"] == 7 and len(p1["items"]) == 3 and len(p3["items"]) == 1 and p1["items"][0]["due_at"] < p1["items"][-1]["due_at"]
    assert client.get("/api/follow-ups?scope=all&range=all&page_size=500").json()["page_size"] == 100, "sayfa boyutu sınırlıdır"
    assert staff.get("/api/follow-ups?range=all").json()["total"] == 0, "başkasının takipleri 'benim' listemde yok"
    assert staff.get("/api/follow-ups?range=all&scope=all").json()["total"] == 7


def test_todays_and_overdue_follow_ups_flow_into_call_today_with_reasons(client, db):
    today_b = _analyzed_business(client, db, name="Bugün Aranacak")
    late_b = _analyzed_business(client, db, name="Gecikmiş Aranacak")
    later_b = _analyzed_business(client, db, name="İleri Takipli Firma")
    _create(client, today_b, _day(0), "bugün ara")
    _create(client, late_b, _day(-3), "unutulmuş")
    _create(client, later_b, _day(6))
    items = client.get("/api/sales/call-today?limit=50&scope=all").json()["items"]
    by_id = {i["business"]["id"]: i for i in items}
    assert today_b in by_id and late_b in by_id and later_b not in by_id, "takip günü gelmeyen firma listede yok"
    assert any("Bugün takip günü" in r for r in by_id[today_b]["call"]["reasons"])
    assert any("Gecikmiş takip" in r for r in by_id[late_b]["call"]["reasons"]) and by_id[late_b]["business"]["follow_up_state"] == "overdue"
    order = [i["business"]["id"] for i in items]
    assert order.index(late_b) < order.index(today_b), "gecikmiş takip önde"
    # takip tamamlanınca 'bugün' listesinden düşer
    fu_id = _ids(client, range="today")[0][0]
    client.post(f"/api/follow-ups/{fu_id}/complete", json={"result": "Görüşüldü"})
    assert today_b not in [i["business"]["id"] for i in client.get("/api/sales/call-today?limit=50&scope=all").json()["items"]]


def test_follow_up_activity_is_user_attributed(client, login_as, db):
    staff = login_as("calisan", name="Takipçi")
    bid = _analyzed_business(client, db, name="Kayıtlı Takip")
    fu = _create(staff, bid, _day(1), "not")
    staff.post(f"/api/follow-ups/{fu['id']}/complete", json={"result": "Görüşüldü"})
    acts = db.query(CrmActivity).filter_by(business_id=bid).order_by(CrmActivity.id).all()
    kinds = [(a.type, a.user_id) for a in acts if a.type.startswith("follow_up")]
    assert kinds == [("follow_up", staff.user.id), ("follow_up_done", staff.user.id)]
    log = client.get("/api/admin/activity?action=crm_follow_up").json()
    assert log["total"] >= 1 and log["items"][0]["user_name"] == "Takipçi"


def test_call_today_items_carry_their_source_and_detail_lists_follow_ups(client, db):
    fresh = _analyzed_business(client, db, name="Yalnız Analiz")
    contacted = _analyzed_business(client, db, name="Temaslı Firma")
    late = _analyzed_business(client, db, name="Gecikmiş Kaynak")
    client.post(f"/api/crm/{contacted}/contact", json={"channel": "arama", "result": "Görüşüldü"})
    from packages.db.models import Business

    db.query(Business).filter_by(id=contacted).update({"last_contact_at": NOW() - timedelta(days=3)})  # dünden önce görüşülmüş (bugün görüşülenler listeden elenir)
    db.commit()
    _create(client, late, _day(-1))
    by_id = {i["business"]["id"]: i for i in client.get("/api/sales/call-today?limit=50&scope=all").json()["items"]}
    keys = lambda bid: [s["key"] for s in by_id[bid]["call"]["sources"]]
    assert keys(fresh) == ["yeni_analiz"] and keys(contacted) == ["temas_sonuclanmamis"] and keys(late) == ["takip_gecikmis"]
    detail = client.get(f"/api/businesses/{late}").json()
    assert [f["status"] for f in detail["follow_ups"]] == ["Bekliyor"] and detail["follow_ups"][0]["date_state"] == "overdue"
    client.post(f"/api/follow-ups/{detail['follow_ups'][0]['id']}/complete", json={"result": "Görüşüldü"})
    after = client.get(f"/api/businesses/{late}").json()["follow_ups"]
    assert [f["status"] for f in after] == ["Tamamlandı"] and after[0]["date_state"] is None


def test_crm_list_is_paginated(client, db):
    for n in range(5):
        bid = _analyzed_business(client, db, name=f"Sayfalı CRM {n}")
        client.post(f"/api/businesses/{bid}/crm", json={"stage": "Yeni"})
    p1 = client.get("/api/crm?page=1&page_size=2").json()
    p3 = client.get("/api/crm?page=3&page_size=2").json()
    assert p1["filtered_total"] == 5 and p1["pages"] == 3 and len(p1["items"]) == 2 and len(p3["items"]) == 1 and p3["page"] == 3
    seen = {x["id"] for pg in (1, 2, 3) for x in client.get(f"/api/crm?page={pg}&page_size=2").json()["items"]}
    assert len(seen) == 5, "sayfalar birbirini tekrar etmez, hiçbir kayıt atlanmaz"
    assert client.get("/api/crm?page=0&page_size=9999").json()["page_size"] == 200 and client.get("/api/crm").json()["page_size"] == 50


def test_follow_up_driven_firms_are_listed_before_higher_scored_fresh_leads(client, db):
    fresh = [_analyzed_business(client, db, name=f"Taze Aday {n}") for n in range(3)]
    due_today = _analyzed_business(client, db, name="Bugün Takipli Düşük")
    overdue = _analyzed_business(client, db, name="Gecikmiş Takipli Düşük")
    _create(client, due_today, _day(0))
    _create(client, overdue, _day(-4))
    order = [i["business"]["id"] for i in client.get("/api/sales/call-today?limit=50&scope=all").json()["items"]]
    assert order[:2] == [overdue, due_today], "takibi gelen firmalar: önce gecikmiş, sonra bugünkü; kalanlar puana göre"
    assert set(fresh) <= set(order[2:])
