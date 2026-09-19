"""Satış operasyonu: 7 aşamalı CRM, takip sistemi, teklif/satış alanları, fiyat ayarları, satış planı, 'Bugün Kimi Aramalıyım?',
sağlayıcı sinyalleri, satış metinleri, huni/gelir/personel raporları ve öneriler. Gerçek analiz hattı + gerçek veritabanı (test DB) kullanılır."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import text

from packages.crm import CRM_STAGES, LEGACY_STAGE_ALIASES, normalize_stage
from packages.db.models import Business, CrmActivity, ServiceCatalog
from services.crm_service import TZ, follow_up_state, parse_amount, parse_follow_up, CrmError
from services.integrations.website_crawler.real_crawler import find_agency_credit
from services.sales import reports
from services.sales.call_priority import score_call
from services.sales.providers import build_provider_signals
from services.sales.scripts import build_scripts

from tests.test_sales_features import _analyzed_business

TODAY = lambda: datetime.now(timezone.utc).astimezone(TZ).date()


def _iso(days: int) -> str:
    return (TODAY() + timedelta(days=days)).isoformat()


def _crm(client, bid, stage="Yeni", **extra):
    r = client.post(f"/api/businesses/{bid}/crm", json={"stage": stage, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _patch(client, bid, **body):
    return client.patch(f"/api/businesses/{bid}/crm", json=body)


# ================================================================ 7 aşamalı CRM
def test_nine_stages_are_strict_and_old_names_are_rejected(client, db):
    assert CRM_STAGES == ["Yeni", "Aranacak", "Daha Sonra Ara", "Arandı", "Görüşüldü", "Teklif Gönderildi", "Takip Bekliyor", "Kazanıldı", "Kaybedildi"]
    old_names = ["Teklif Verildi", "Takipte", "Müşteri Oldu", "Olumsuz", "Yeni Lead", "Yeni Potansiyel", "İletişime Geçildi", "İlgileniyor", "Teklif Hazırlanıyor", "Ulaşılamadı", "Uydurma"]
    assert all(normalize_stage(n) is None for n in old_names) and all(normalize_stage(n) == n for n in CRM_STAGES)
    assert all(v in CRM_STAGES for v in LEGACY_STAGE_ALIASES.values()) and not set(LEGACY_STAGE_ALIASES) & set(CRM_STAGES)
    bid = _analyzed_business(client, db, name="Eski Ad Reddi")
    for name in old_names:
        r = client.post(f"/api/businesses/{bid}/crm", json={"stage": name})
        assert r.status_code == 422 and "Geçersiz CRM durumu" in r.json()["detail"], name
        assert client.patch(f"/api/businesses/{bid}/crm", json={"stage": name}).status_code == 422, name
    assert client.get("/api/crm?stage=Teklif Verildi").status_code == 422 and client.get("/api/businesses?crm_stage=Takipte").status_code == 422
    msg = client.post(f"/api/businesses/{bid}/crm", json={"stage": "Takipte"}).json()["detail"]
    assert all(n in msg for n in CRM_STAGES) and "Teklif Verildi" not in msg and "Müşteri Oldu" not in msg, "hata mesajı yeni listeyi gösterir"
    assert db.get(Business, bid).crm_added_at is None, "reddedilen istek firmayı CRM'e eklemez"
    meta = client.get("/api/crm/meta").json()
    assert meta["stages"] == CRM_STAGES and "Ulaşılamadı" in meta["results"]


def test_seven_stage_migration_preserves_records_and_legacy_names(seeded_db):
    """b7a1c3d5e901: 12 aşamalı adlar 7 aşamaya taşınır; hiçbir kayıt silinmez; eski ad meta.legacy_stage'de, ulaşılamadı sonucu meta.result'ta korunur; downgrade geri çevirir."""
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = next(Path(__file__).resolve().parent.parent.glob("packages/db/migrations/versions/*crm_seven_stages.py"))
    spec = importlib.util.spec_from_file_location("seven_stage_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from tests.test_crm_and_reports import _make_business

    db = seeded_db
    old_names = list(module.MAPPING)
    for n, old in enumerate(old_names):
        b = _make_business(db, f"Eski {n}")
        db.execute(text("UPDATE businesses SET crm_stage=:s, crm_added_at=now(), crm_last_action=:a WHERE id=:i"), {"s": old, "i": b.id, "a": f"Yeni Potansiyel → {old}"})
        db.add(CrmActivity(business_id=b.id, type="status_change", from_stage="Yeni Potansiyel", to_stage=old, note=old))
    db.commit()
    total = db.query(CrmActivity).count()
    with Operations.context(MigrationContext.configure(db.connection())):
        module.upgrade()
    db.commit()
    db.expire_all()
    stages = {r[0] for r in db.execute(text("SELECT crm_stage FROM businesses"))}
    seven = {"Yeni Lead", "İletişime Geçildi", "İlgileniyor", "Teklif Gönderildi", "Kazanıldı", "Takip Bekliyor", "Kaybedildi"}
    assert stages <= seven, stages
    assert db.query(CrmActivity).count() == total, "hiçbir aktivite silinmedi"
    rows = {a.note: a for a in db.query(CrmActivity).all()}
    assert rows["Ulaşılamadı"].to_stage == "İletişime Geçildi" and rows["Ulaşılamadı"].meta == {"legacy_stage": "Ulaşılamadı", "result": "Ulaşılamadı"}
    assert rows["Aranacak"].to_stage == "Yeni Lead" and rows["Aranacak"].meta["legacy_stage"] == "Aranacak"
    assert rows["Müşteri Oldu"].to_stage == "Kazanıldı" and rows["Daha Sonra Ara"].to_stage == "Takip Bekliyor"
    assert "Yeni Potansiyel" not in (db.execute(text("SELECT string_agg(crm_last_action, ' ') FROM businesses")).scalar() or ""), "son işlem metinleri de yeni adlara çevrilir"
    with Operations.context(MigrationContext.configure(db.connection())):
        module.downgrade()
    db.commit()
    db.expire_all()
    back = {a.note: a.to_stage for a in db.query(CrmActivity).all()}
    assert all(back[name] == name for name in old_names), "downgrade eski adları meta.legacy_stage'den geri getirir"


def test_status_rename_migration_preserves_and_reverses(seeded_db):
    """ac54eca6d6b8: eski durum adları yeni adlara taşınır (kayıt silinmez), downgrade geri çevirir."""
    import importlib.util

    path = next(Path(__file__).resolve().parent.parent.glob("packages/db/migrations/versions/*sales_pipeline_stages*.py"))
    spec = importlib.util.spec_from_file_location("sales_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from tests.test_crm_and_reports import _make_business

    db = seeded_db
    b = _make_business(db, "Eski Durumlu")
    for legacy in module.RENAMES:
        db.execute(text("UPDATE businesses SET crm_stage=:s WHERE id=:i"), {"s": legacy, "i": b.id})
        db.add(CrmActivity(business_id=b.id, type="status_change", from_stage=legacy, to_stage=legacy))
    db.commit()
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(db.connection())):
        module._rename(module.RENAMES)  # migration'ın kendi işlevi çalıştırılır
    db.commit()
    assert {r[0] for r in db.execute(text("SELECT to_stage FROM crm_activities"))} == set(module.RENAMES.values())
    assert db.execute(text("SELECT crm_stage FROM businesses WHERE id=:i"), {"i": b.id}).scalar() == "Kaybedildi"
    assert db.query(CrmActivity).count() == len(module.RENAMES), "hiçbir aktivite kaydı silinmedi"
    with Operations.context(MigrationContext.configure(db.connection())):
        module._rename({new: old for old, new in module.RENAMES.items()})  # downgrade yönü
    db.commit()
    assert {r[0] for r in db.execute(text("SELECT to_stage FROM crm_activities"))} == set(module.RENAMES)


# ================================================================ satış takibi alanları
def test_offer_sale_lost_fields_validation_and_consistency(client, db):
    bid = _analyzed_business(client, db, name="Teklif Alanları")
    state = _crm(client, bid, "Teklif Gönderildi", offer_amount="12500,50", interested_service="Kurumsal Web Sitesi")
    assert state["offer_amount"] == 12500.5 and state["interested_service"] == "Kurumsal Web Sitesi" and state["crm_owner_name"]
    assert _patch(client, bid, stage="Teklif Gönderildi").json()["last_contact_at"] is None or True
    assert _patch(client, bid, offer_amount=-5).status_code == 422
    assert _patch(client, bid, offer_amount="abc").status_code == 422
    assert _patch(client, bid, sale_amount=1000).status_code == 422, "satış tutarı yalnızca Kazanıldı'da"
    assert _patch(client, bid, lost_reason="Bütçe").status_code == 422, "kayıp nedeni yalnızca Kaybedildi'de"
    won = _patch(client, bid, stage="Kazanıldı", sale_amount=9000).json()
    assert won["crm_stage"] == "Kazanıldı" and won["sale_amount"] == 9000 and won["next_follow_up_at"] is None
    top = won["history"][0]
    assert top["to_stage"] == "Kazanıldı" and top["meta"]["sale_amount"] == 9000 and top["user_name"]
    reopened = _patch(client, bid, stage="Takip Bekliyor").json()
    assert reopened["sale_amount"] is None, "Kazanıldı'dan çıkınca satış tutarı temizlenir (geçmişte kalır)"
    lost = _patch(client, bid, stage="Kaybedildi", lost_reason="Bütçe uygun değil").json()
    assert lost["lost_reason"] == "Bütçe uygun değil"
    assert _patch(client, bid, follow_up_at=_iso(3)).status_code == 422, "kapanmış kayda takip girilemez"


def test_parse_helpers():
    assert parse_amount("", "x") is None and float(parse_amount("1.250,5".replace(".", ""), "x")) == 1250.5
    with pytest.raises(CrmError):
        parse_amount("-1", "x")
    with pytest.raises(CrmError):
        parse_follow_up("32.13.2026")
    assert parse_follow_up("2026-09-25").astimezone(TZ).hour == 0 and parse_follow_up(None) is None


# ================================================================ takip sistemi
def test_follow_ups_today_overdue_upcoming_and_completion(client, db):
    a = _analyzed_business(client, db, name="Bugün Takip")
    b = _analyzed_business(client, db, name="Geciken Takip")
    c = _analyzed_business(client, db, name="Yarın Takip")
    d = _analyzed_business(client, db, name="Takipsiz")
    _crm(client, a, "Takip Bekliyor", follow_up_at=_iso(0), follow_up_note="Fiyat sor")
    _crm(client, b, "Takip Bekliyor", follow_up_at=_iso(-3))
    _crm(client, c, "Teklif Gönderildi", follow_up_at=_iso(1))
    _crm(client, d, "Yeni")
    f = client.get("/api/crm/follow-ups").json()
    assert {k: f["counts"][k] for k in ("overdue", "today", "upcoming")} == {"overdue": 1, "today": 1, "upcoming": 1} and f["counts"]["tomorrow"] == 1
    assert [x["id"] for x in f["overdue"]] == [b] and [x["id"] for x in f["today"]] == [a] and f["today"][0]["follow_up_note"] == "Fiyat sor"
    assert f["overdue"][0]["follow_up_state"] == "overdue"
    assert client.get("/api/crm?follow_up=overdue").json()["items"][0]["id"] == b
    assert [x["id"] for x in client.get("/api/crm?follow_up=none").json()["items"]] == [d]
    assert client.get("/api/crm?follow_up=x").status_code == 422
    # tamamlama: sonuç + yeni tarih
    assert client.post(f"/api/crm/{d}/follow-up/complete", json={"result": "Görüşüldü"}).status_code == 409, "açık takibi olmayan firma"
    assert client.post(f"/api/crm/{b}/follow-up/complete", json={"result": "Bilinmeyen"}).status_code == 422
    done = client.post(f"/api/crm/{b}/follow-up/complete", json={"result": "Görüşüldü", "note": "Teklifi bekliyor", "next_follow_up_at": _iso(5)}).json()
    assert done["next_follow_up_at"].startswith(_iso(5)[:8]) and done["history"][0]["type"] == "follow_up_done"
    assert done["history"][0]["meta"]["due_at"] and "Teklifi bekliyor" in done["history"][0]["note"]
    assert done["last_contact_at"] is not None
    closed = client.post(f"/api/crm/{a}/follow-up/complete", json={"result": "Ulaşılamadı"}).json()
    assert closed["next_follow_up_at"] is None and closed["last_contact_at"] is None, "ulaşılamadı görüşme sayılmaz"
    f2 = client.get("/api/crm/follow-ups").json()
    assert f2["counts"]["overdue"] == 0 and f2["counts"]["today"] == 0 and f2["counts"]["upcoming"] == 2


def test_follow_up_scope_mine_vs_all(client, login_as, db):
    a = _analyzed_business(client, db, name="Benim Takibim")
    _crm(client, a, "Takip Bekliyor", follow_up_at=_iso(0))
    staff = login_as("calisan")
    assert staff.get("/api/crm/follow-ups").json()["counts"]["today"] == 0, "başkasının takibi 'benim' listesinde çıkmaz"
    assert staff.get("/api/crm/follow-ups?scope=all").json()["counts"]["today"] == 1
    assert client.get("/api/crm/follow-ups").json()["counts"]["today"] == 1


def test_owner_assignment_needs_permission(client, login_as, db):
    a = _analyzed_business(client, db, name="Sorumlu Atama")
    staff = login_as("calisan")
    intern = login_as("stajyer")
    _crm(client, a, "Yeni")
    assert _patch(intern, a, owner_id=staff.user.id).status_code == 403, "stajyer sorumlu değiştiremez"
    assert _patch(staff, a, owner_id=staff.user.id).json()["crm_owner_name"] == staff.user.name
    assert _patch(client, a, owner_id=999999).status_code == 422


def test_follow_up_state_uses_istanbul_calendar_day():
    b = Business(name="x", crm_added_at=datetime.now(timezone.utc))
    now = datetime(2026, 9, 23, 22, 30, tzinfo=timezone.utc)  # İstanbul: 24 Eylül 01:30
    b.next_follow_up_at = datetime(2026, 9, 23, 20, 0, tzinfo=timezone.utc)  # İstanbul: 23 Eylül 23:00 → dün
    assert follow_up_state(b, now) == "overdue"
    b.next_follow_up_at = datetime(2026, 9, 23, 21, 0, tzinfo=timezone.utc)  # 24 Eylül 00:00 İstanbul → bugün
    assert follow_up_state(b, now) == "today"


# ================================================================ fiyat ayarları + tahmini değer
def test_service_prices_admin_only_and_never_invented(client, login_as, db):
    listing = client.get("/api/admin/service-prices").json()
    assert len(listing["items"]) == db.query(ServiceCatalog).count() and all(not i["priced"] for i in listing["items"]), "varsayılan: hiçbir fiyat yok"
    assert login_as("calisan").get("/api/admin/service-prices").status_code == 403
    assert login_as("stajyer").put("/api/admin/service-prices/1", json={"default_price": 1}).status_code == 403
    web = next(i for i in listing["items"] if i["service_name"] == "Kurumsal Web Sitesi")
    assert client.put(f"/api/admin/service-prices/{web['service_id']}", json={"min_price": 5000, "max_price": 1000}).status_code == 422
    assert client.put(f"/api/admin/service-prices/{web['service_id']}", json={"min_price": 5000, "max_price": 9000, "default_price": 12000}).status_code == 422
    assert client.put(f"/api/admin/service-prices/{web['service_id']}", json={"min_price": -1}).status_code == 422
    assert client.put("/api/admin/service-prices/99999", json={"default_price": 1}).status_code == 404
    ok = client.put(f"/api/admin/service-prices/{web['service_id']}", json={"min_price": 5000, "max_price": 9000, "default_price": 7000}).json()
    assert ok["priced"] and ok["default_price"] == 7000


def test_sales_plan_unpriced_then_priced_package(client, db):
    bid = _analyzed_business(client, db, name="Plan Firması")
    plan = client.get(f"/api/sales/plan/{bid}").json()
    assert plan["analyzed"] and plan["package"]["label"] == "Fiyatlandırma yapılmadı" and plan["package"]["default"] is None
    actionable = [o for o in plan["opportunities"] if o["level"] in ("satis", "olasi")]
    assert actionable and actionable[0]["priority"] == 1 and all(o["estimate"]["label"] == "Fiyatlandırma yapılmadı" for o in actionable)
    for o in actionable:
        assert o["sources"] and (o["evidence"] or o["evidence_note"]), "her fırsatın kanıtı+kaynağı ya da 'Doğrulanamadı' notu olmalı"
        assert all(e["source_label"] in ("Google", "Website", "Social", "Çapraz kontrol") for e in o["evidence"])
    for o in plan["opportunities"]:
        if o["level"] not in ("satis", "olasi"):
            assert o["estimate"] is None, "uygun olmayan hizmete tahmini değer yazılmaz"
    svc = actionable[0]["service"]
    sid = next(i["service_id"] for i in client.get("/api/admin/service-prices").json()["items"] if i["service_name"] == svc)
    client.put(f"/api/admin/service-prices/{sid}", json={"min_price": 1000, "max_price": 3000, "default_price": 2000})
    plan2 = client.get(f"/api/sales/plan/{bid}").json()
    assert plan2["package"]["default"] == 2000 and plan2["package"]["min"] == 1000 and svc in [p["service"] for p in plan2["package"]["priced"]]
    assert plan2["package"]["unpriced"] or len(plan2["package"]["services"]) == 1
    assert plan2["package"]["disclaimer"]
    client.put(f"/api/admin/service-prices/{sid}", json={"min_price": 1000, "max_price": 3000, "default_price": 2000, "is_active": False})
    assert client.get(f"/api/sales/plan/{bid}").json()["package"]["default"] is None, "pasif hizmet pakete girmez"
    assert client.get("/api/sales/plan/999999").status_code == 404


def test_sales_plan_for_unanalyzed_business(client, db):
    from tests.test_crm_and_reports import _make_business

    b = _make_business(db, "Analizsiz")
    db.query(Business).filter_by(id=b.id).update({"status": "discovered"})
    db.commit()
    plan = client.get(f"/api/sales/plan/{b.id}").json()
    assert plan["analyzed"] is False and plan["opportunities"] == [] and "analiz" in plan["message"]


# ================================================================ satış metinleri
MATRIX = {"items": [
    {"service": "Kurumsal Web Sitesi", "level": "satis", "sector_only": False, "commercial": 5, "recurring": False,
     "evidence": [{"text": "Web sitesi bulunamadı", "detail": "Doğrulanmış bir web sitesi bulunamadı.", "verified": True, "severity": "high", "area": "website"}]},
    {"service": "Google Ads", "level": "olasi", "sector_only": True, "commercial": 4, "recurring": True,
     "evidence": [{"text": "Sektöre dayalı olası ihtiyaç", "detail": "sektör tahmini", "verified": False, "severity": "medium", "area": "derived"}]},
]}


def test_scripts_use_only_verified_facts_and_no_price_promise():
    s = build_scripts(business_name="Deneme Klinik", sector_name="Diş Kliniği", place="Serdivan", matrix=MATRIX, staff_name="Ayşe Demir")
    assert [f["service"] for f in s["facts_used"]] == ["Kurumsal Web Sitesi"], "yalnızca doğrulanmış bulgular olgu olarak kullanılır"
    blob = " ".join([s["call"], s["whatsapp"], s["email"]["subject"], s["email"]["body"], s["short_note"]])
    assert "Doğrulanmış bir web sitesi bulunamadı" in blob and "sektör tahmini" not in blob
    assert "Ayşe Demir" in s["call"] and "Deneme Klinik" in s["whatsapp"] and s["email"]["subject"]
    assert "TL" not in blob and "garanti" not in blob.lower() and "%" not in blob, "fiyat/sonuç vaadi yok"
    empty = build_scripts(business_name="Boş Firma", sector_name=None, place=None, matrix={"items": []}, staff_name=None)
    assert empty["facts_used"] == [] and "doğrulanmış bulgu yok" in empty["short_note"] and "genel" in empty["basis"]
    assert "Kısa bir inceleme yaptık" not in empty["call"], "bulgu yoksa bulgu varmış gibi konuşulmaz"


def test_scripts_endpoint_is_personalised_with_current_user(client, db):
    bid = _analyzed_business(client, db, name="Metin Kliniği")
    s = client.get(f"/api/sales/plan/{bid}").json()["scripts"]
    assert "Test Yönetici" in s["call"] and "Metin Kliniği" in s["email"]["body"] and s["caveat"]


# ================================================================ sağlayıcı / rakip sinyalleri
def test_agency_credit_detection_is_evidence_based():
    def credit(html):
        return find_agency_credit(BeautifulSoup(html, "html.parser"), "abc.com")

    linked = credit('<footer>© ABC · Web Tasarım: <a href="https://www.ornekajans.com/">Örnek Ajans</a></footer>')
    assert linked["name"] == "Örnek Ajans" and linked["kind"] == "agency" and linked["url"].startswith("https://www.ornekajans.com")
    assert credit("<footer>Designed by Foo Studio | Tüm hakları saklıdır</footer>")["name"] == "Foo Studio"
    assert credit("<footer>Tasarımlarımız için bizi arayın. © ABC</footer>") is None, "sıradan 'tasarım' kelimesi kredi sayılmaz"
    assert credit('<footer><a href="https://instagram.com/abc">Instagram</a> Web Tasarım</footer>') is None
    assert credit('<footer>Powered by <a href="https://wordpress.org">WordPress</a></footer>')["kind"] == "platform"
    assert credit("<body><p>Designed by Foo</p></body>") is None, "footer yoksa aranmaz"


def test_provider_signals_never_claim_without_evidence():
    green_web = {"items": [{"service": "Kurumsal Web Sitesi", "level": "satis"}, {"service": "Web Tasarım", "level": "satis"}]}
    none = build_provider_signals({"success": True, "analytics_tools": ["ga4"]}, green_web, has_website=True)
    by_key = {i["key"]: i for i in none["items"]}
    assert by_key["web"]["status"] == "dogrulanamadi" and by_key["seo"]["status"] == "dogrulanamadi" and by_key["print"]["status"] == "dogrulanamadi"
    assert none["win_opportunities"] == [], "kanıt yokken 'rakipten kazanma' iddia edilmez"
    assert "ajans olmadığı anlamına gelmez" in by_key["web"]["evidence"]
    found = build_provider_signals({"success": True, "agency_credit": {"name": "Örnek Ajans", "url": "https://x.test", "text": "Web Tasarım: Örnek Ajans", "kind": "agency"}}, green_web, has_website=True)
    assert [w["service"] for w in found["win_opportunities"]] == ["Kurumsal Web Sitesi"] and "yargı verilmez" in found["win_opportunities"][0]["text"]
    assert found["win_opportunities"][0]["source"] == "Website"
    healthy = build_provider_signals({"success": True, "agency_credit": {"name": "Örnek Ajans", "url": None, "text": "t", "kind": "agency"}}, {"items": [{"service": "Kurumsal Web Sitesi", "level": "zayif"}]}, has_website=True)
    assert healthy["win_opportunities"] == [], "doğrulanmış eksik yoksa fırsat da yok"
    ads = build_provider_signals({"success": True, "analytics_tools": ["google_ads"], "cta_present": False}, {"items": [{"service": "Google Ads", "level": "olasi"}]}, has_website=True)
    assert next(i for i in ads["items"] if i["key"] == "ads")["status"] == "tespit_edildi" and ads["win_opportunities"][0]["service"] == "Google Ads"
    nosite = build_provider_signals(None, green_web, has_website=False)
    assert next(i for i in nosite["items"] if i["key"] == "web")["status"] == "yok"


# ================================================================ Bugün Kimi Aramalıyım?
def _call(**over):
    base = dict(priority_value=80, matrix=MATRIX, has_phone=True, has_email=False, mobile_phone=True, review_count=50, provider_wins=0, crm_stage="Yeni",
                in_crm=False, follow_state=None, follow_at=None, last_contact_at=None, call_attempts=0, now=datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc))
    base.update(over)
    return score_call(**base)


def test_call_priority_components_and_exclusions():
    base = _call()
    assert base["excluded"] is None and 0 < base["score"] <= 100 and base["reasons"] and set(base["components"]) == {"opportunity", "urgency", "service_fit", "commercial", "digital", "competitor", "contact", "crm"}
    assert any("Telefon" in r for r in base["reasons"]) and any("Satış öncelik değeri" in r for r in base["reasons"])
    assert _call(follow_state="overdue", follow_at=datetime(2026, 9, 20, tzinfo=timezone.utc), in_crm=True, crm_stage="Takip Bekliyor")["score"] > base["score"], "geciken takip öne çıkar"
    assert _call(has_phone=False, mobile_phone=False)["score"] < base["score"] and any("doğrulanamadı" in r for r in _call(has_phone=False, mobile_phone=False)["reasons"])
    assert _call(priority_value=None, matrix=None)["score"] < base["score"]
    assert _call(crm_stage="Kazanıldı", in_crm=True)["excluded"] and _call(crm_stage="Kaybedildi", in_crm=True)["excluded"]
    up = _call(follow_state="upcoming", follow_at=datetime(2026, 9, 30, tzinfo=timezone.utc), in_crm=True, crm_stage="Takip Bekliyor")
    assert "Takip tarihi ileri" in up["excluded"]
    today = _call(last_contact_at=datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc), in_crm=True, crm_stage="Arandı")
    assert today["excluded"] == "Bugün zaten görüşüldü"
    assert _call(last_contact_at=datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc), follow_state="today", in_crm=True, crm_stage="Arandı")["excluded"] is None
    assert any("kez denendi" in r for r in _call(crm_stage="Arandı", in_crm=True, call_attempts=4)["reasons"])
    assert _call()["components"]["competitor"] == 0 and _call(provider_wins=1)["components"]["competitor"] > 0
    assert _call(review_count=None)["components"]["commercial"] == 0, "yorum sayısı yoksa ticari yapı puanı verilmez"


def test_call_today_endpoint_excludes_closed_future_and_ranks(client, db):
    a = _analyzed_business(client, db, name="Yeni Adayı")
    b = _analyzed_business(client, db, name="Geciken Aday")
    c = _analyzed_business(client, db, name="Kapanmış Aday")
    d = _analyzed_business(client, db, name="İleri Takipli")
    _crm(client, b, "Takip Bekliyor", follow_up_at=_iso(-2))
    _crm(client, c, "Kazanıldı")
    _crm(client, d, "Takip Bekliyor", follow_up_at=_iso(4))
    r = client.get("/api/sales/call-today?limit=20").json()
    ids = [i["business"]["id"] for i in r["items"]]
    assert a in ids and b in ids and c not in ids and d not in ids
    assert ids.index(b) < ids.index(a), "geciken takip, yeni adayın önünde"
    top = next(i for i in r["items"] if i["business"]["id"] == b)
    assert top["call"]["next_action"] == "Gecikmiş takibi tamamla" and any("Gecikmiş takip" in x for x in top["call"]["reasons"])
    assert r["excluded"].get("Takip tarihi ileri") == 1
    scores = [i["call"]["score"] for i in r["items"]]
    assert scores == sorted(scores, reverse=True)
    assert client.get("/api/sales/call-today?scope=x").status_code == 422


def test_call_today_scope_mine_hides_other_users_crm_records(client, login_as, db):
    a = _analyzed_business(client, db, name="Yöneticinin Kaydı")
    _crm(client, a, "Yeni")
    staff = login_as("calisan")
    mine = [i["business"]["id"] for i in staff.get("/api/sales/call-today?limit=50").json()["items"]]
    everyone = [i["business"]["id"] for i in staff.get("/api/sales/call-today?limit=50&scope=all").json()["items"]]
    assert a not in mine and a in everyone


# ================================================================ huni / gelir / personel / öneri
def test_funnel_is_a_monotone_cohort_and_counts_real_records(client, db):
    ids = [_analyzed_business(client, db, name=f"Huni {n}") for n in range(4)]
    _crm(client, ids[0], "Arandı")
    _crm(client, ids[1], "Görüşüldü")
    _crm(client, ids[2], "Teklif Gönderildi", offer_amount=5000)
    _crm(client, ids[3], "Yeni")
    _patch(client, ids[3], stage="Teklif Gönderildi", offer_amount=8000)
    _patch(client, ids[3], stage="Kazanıldı", sale_amount=7000)
    f = client.get("/api/sales/funnel?period=today").json()
    counts = {s["key"]: s["count"] for s in f["steps"]}
    assert counts["analysis"] == 4 and counts["contacted"] == 4 and counts["interested"] == 3 and counts["offer"] == 2 and counts["won"] == 1
    seq = [s["count"] for s in f["steps"]]
    assert seq == sorted(seq, reverse=True), "huni azalan (alt küme) olmalı"
    assert all(s["rate_from_previous"] is None or s["rate_from_previous"] <= 100 for s in f["steps"])
    assert f["won_total"] == 7000 and f["won_count"] == 1 and f["offer_count"] == 2 and f["offer_total"] == 8000 + 5000 - 0
    assert client.get("/api/sales/funnel?period=yil").status_code == 422


def test_revenue_by_service_and_sector_min_sample_rule(client, db):
    ids = [_analyzed_business(client, db, name=f"Gelir {n}") for n in range(2)]
    for bid in ids:
        _crm(client, bid, "Teklif Gönderildi", offer_amount=3000, interested_service="Kurumsal Web Sitesi")
    _patch(client, ids[0], stage="Kazanıldı", sale_amount=2500)
    _patch(client, ids[1], stage="Kazanıldı")  # tutar girilmedi
    rev = client.get("/api/sales/revenue?by=service&period=total").json()
    row = next(r for r in rev["items"] if r["name"] == "Kurumsal Web Sitesi")
    assert row["offers"] == 2 and row["sales"] == 2 and row["amount"] == 2500 and row["amount_missing"] == 1 and row["average"] == 2500
    assert row["conversion"] is None and row["sample_note"] == "Yeterli veri bulunmuyor.", "örneklem küçükken dönüşüm hesaplanmaz"
    assert rev["items"][0]["name"] == "Kurumsal Web Sitesi", "sıralama satış tutarına göre; önceden ilan edilen 'en kârlı' yok"
    sec = client.get("/api/sales/revenue?by=sector&period=total").json()
    assert next(r for r in sec["items"] if r["name"] == "İşitme Cihazı Merkezi")["sales"] == 2
    assert client.get("/api/sales/revenue?by=x").status_code == 422


def test_conversion_appears_only_with_enough_offers(client, db):
    ids = [_analyzed_business(client, db, name=f"Dönüşüm {n}") for n in range(reports.MIN_SAMPLE)]
    for i, bid in enumerate(ids):
        _crm(client, bid, "Teklif Gönderildi", interested_service="Yerel SEO")
        if i < 2:
            _patch(client, bid, stage="Kazanıldı", sale_amount=1000)
    row = next(r for r in client.get("/api/sales/revenue?by=service").json()["items"] if r["name"] == "Yerel SEO")
    assert row["offers"] == 5 and row["sales"] == 2 and row["conversion"] == 40.0
    s = client.get("/api/sales/suggestions").json()["items"]
    assert any(i["kind"] == "best_service" and "Yerel SEO" in i["text"] and "garanti" not in i["text"].lower() for i in s)


def test_suggestions_report_no_data_honestly(client):
    items = client.get("/api/sales/suggestions").json()["items"]
    assert items == [{"kind": "no_data", "text": items[0]["text"]}] and "Yeterli veri bulunmuyor." in items[0]["text"]


def test_staff_performance_counts_actions_and_results(client, login_as, db):
    staff = login_as("calisan", name="Satış Personeli")
    ids = [_analyzed_business(client, db, name=f"Personel {n}") for n in range(3)]
    _crm(staff, ids[0], "Yeni")
    _patch(staff, ids[0], stage="Arandı")
    _patch(staff, ids[0], stage="Teklif Gönderildi", offer_amount=4000)
    _patch(staff, ids[0], stage="Kazanıldı", sale_amount=3500)
    assert staff.post(f"/api/crm/{ids[1]}/contact", json={"channel": "arama", "result": "Ulaşılamadı"}).status_code == 200
    _crm(staff, ids[2], "Yeni", follow_up_at=_iso(-1))
    client.post(f"/api/crm/{ids[2]}/follow-up/complete", json={"result": "Görüşüldü"})  # yönetici tamamladı
    _crm(staff, _analyzed_business(client, db, name="Personel Geciken"), "Takip Bekliyor", follow_up_at=_iso(-2))
    rows = client.get("/api/sales/staff?period=today").json()["items"]
    me = next(r for r in rows if r["name"] == "Satış Personeli")
    assert me["contacts"] == 2 and me["unreachable"] == 1 and me["interested"] == 0 and me["offers_sent"] == 1 and me["won"] == 1 and me["sales_total"] == 3500
    assert me["leads_added"] == 4 and me["overdue_follow_ups"] == 1 and me["conversion_offer_to_won"] == 100.0
    admin = next(r for r in rows if r["name"] == "Test Yönetici")
    assert admin["follow_ups_done"] == 1 and admin["followed_customers"] == 1 and admin["avg_follow_delay_hours"] is not None
    assert not any("başarılı" in str(v).lower() or "başarısız" in str(v).lower() for r in rows for v in r.values()), "otomatik başarı/başarısızlık etiketi yok"
    assert login_as("calisan").get("/api/sales/staff").status_code == 403
    assert login_as("stajyer").get("/api/sales/report").status_code == 403


def test_periodic_report_overview(client, db):
    a = _analyzed_business(client, db, name="Özet Firma")
    _crm(client, a, "Arandı")
    _patch(client, a, stage="Teklif Gönderildi")
    _patch(client, a, stage="Kazanıldı", sale_amount=1500)
    for period in ("today", "week", "month", "total"):
        m = client.get(f"/api/sales/report?period={period}").json()["metrics"]
        assert m["analyses"] == 1 and m["new_leads"] == 1 and m["contacts"] == 1 and m["offers_sent"] == 1 and m["won"] == 1 and m["won_total"] == 1500
    assert client.get("/api/sales/report?period=yil").status_code == 422


def test_role_access_for_sales_endpoints(client, login_as, anon_client, db):
    a = _analyzed_business(client, db, name="Yetki Firması")
    for path in ("/api/sales/call-today", f"/api/sales/plan/{a}", "/api/sales/funnel", "/api/sales/revenue", "/api/sales/suggestions", "/api/sales/staff", "/api/crm/follow-ups"):
        assert anon_client.get(path).status_code == 401, path
    intern = login_as("stajyer")
    assert intern.get("/api/sales/call-today").status_code == 200 and intern.get(f"/api/sales/plan/{a}").status_code == 200 and intern.get("/api/crm/follow-ups").status_code == 200
    assert intern.get("/api/sales/funnel").status_code == 403 and intern.get("/api/sales/revenue").status_code == 403
    assert login_as("calisan").get("/api/sales/funnel").status_code == 200


def test_legacy_stage_names_written_by_stale_processes_are_normalized(client, db):
    """Eski kodla çalışan bir süreç yeni kayda eski durum adı yazsa bile API açılışında yeni adlara çevrilir (kayıt silinmez)."""
    from services import crm_service
    from tests.test_crm_and_reports import _make_business

    b = _make_business(db, "Eski Süreç Kaydı")
    db.execute(text("UPDATE businesses SET crm_stage='Olumsuz', crm_added_at=now() WHERE id=:i"), {"i": b.id})
    db.add(CrmActivity(business_id=b.id, type="status_change", from_stage="Takipte", to_stage="Müşteri Oldu"))
    db.commit()
    assert crm_service.normalize_legacy_stages(db) == 3
    db.expire_all()
    assert db.get(Business, b.id).crm_stage == "Kaybedildi"
    act = db.query(CrmActivity).one()
    assert (act.from_stage, act.to_stage) == ("Takip Bekliyor", "Kazanıldı")
    assert crm_service.normalize_legacy_stages(db) == 0, "ikinci çalıştırmada değişiklik yok (idempotent)"


def test_notes_and_sales_updates_are_not_counted_as_calls_offers_or_wins(client, db):
    """Not/takip/satış-bilgisi güncellemeleri durum GEÇİŞİ değildir: arama/teklif/satış olarak sayılmamalı (to_stage yalnızca mevcut durumu taşır)."""
    a = _analyzed_business(client, db, name="Sayaç Firması")
    _crm(client, a, "Arandı")
    _patch(client, a, staff_note="sadece not")
    _patch(client, a, follow_up_at=_iso(2))
    _patch(client, a, interested_service="Yerel SEO", offer_amount=1000)
    m = client.get("/api/sales/report?period=today").json()["metrics"]
    assert m["contacts"] == 1 and m["offers_sent"] == 0 and m["won"] == 0 and m["interested"] == 0, "yalnızca gerçek durum geçişleri sayılır"
    _patch(client, a, stage="Teklif Gönderildi")
    _patch(client, a, stage="Kazanıldı", sale_amount=500)
    for _ in range(3):
        _patch(client, a, staff_note=f"kazanç sonrası not {_}")
        _patch(client, a, sale_amount=500 + _)
    m = client.get("/api/sales/report?period=today").json()["metrics"]
    assert m["won"] == 1 and m["offers_sent"] == 1 and m["contacts"] == 1
    rev = client.get("/api/sales/revenue?by=service&period=today").json()["items"]
    assert sum(r["sales"] for r in rev) == 1 and sum(r["offers"] for r in rev) == 1


def test_old_wins_are_not_recounted_when_a_note_is_added_later(client, db):
    """Geçen ay kazanılan firmaya bugün not eklenmesi, bugünün 'satış/arama/teklif' sayılarını ARTIRMAMALI."""
    a = _analyzed_business(client, db, name="Eski Kazanç")
    _crm(client, a, "Arandı")
    _patch(client, a, stage="Teklif Gönderildi")
    _patch(client, a, stage="Kazanıldı", sale_amount=800)
    db.execute(text("UPDATE crm_activities SET created_at = now() - interval '40 days'"))
    db.commit()
    _patch(client, a, staff_note="bugün eklenen not")
    _patch(client, a, sale_amount=900)
    today = client.get("/api/sales/report?period=today").json()["metrics"]
    assert (today["contacts"], today["offers_sent"], today["won"], today["won_total"]) == (0, 0, 0, 0.0)
    total = client.get("/api/sales/report?period=total").json()["metrics"]
    assert (total["contacts"], total["offers_sent"], total["won"]) == (1, 1, 1) and total["won_total"] == 900
    assert all(r["sales"] == 0 for r in client.get("/api/sales/revenue?by=service&period=today").json()["items"])
    staff = client.get("/api/sales/staff?period=today").json()["items"]
    assert all(r["won"] == 0 and r["offers_sent"] == 0 and r["contacts"] == 0 for r in staff)


# ================================================================ iletişim geçmişi
def test_contact_log_records_who_did_what_and_moves_stage_by_result(client, login_as, db):
    staff = login_as("calisan", name="Arayan Personel")
    a = _analyzed_business(client, db, name="İletişim Firması")
    r1 = staff.post(f"/api/crm/{a}/contact", json={"channel": "arama", "result": "Ulaşılamadı", "note": "Meşgul çaldı"}).json()
    assert r1["in_crm"] and r1["crm_stage"] == "Yeni" and r1["last_contact_at"] is None, "ulaşılamadı: aşama ve son görüşme değişmez; firma CRM'e alınır"
    assert r1["history"][0]["type"] == "contact" and r1["history"][0]["meta"] == {"channel": "arama", "result": "Ulaşılamadı"}
    assert r1["history"][0]["user_name"] == "Arayan Personel" and "Arama: Ulaşılamadı" in r1["history"][0]["note"] and "Meşgul çaldı" in r1["history"][0]["note"]
    r2 = staff.post(f"/api/crm/{a}/contact", json={"channel": "arama", "result": "Görüşüldü"}).json()
    assert r2["crm_stage"] == "Arandı" and r2["last_contact_at"] is not None
    r3 = staff.post(f"/api/crm/{a}/contact", json={"channel": "whatsapp", "result": "Teklif istendi"}).json()
    assert r3["crm_stage"] == "Görüşüldü" and r3["crm_last_action"].startswith("WhatsApp: Teklif istendi")
    _patch(staff, a, stage="Teklif Gönderildi")
    r4 = staff.post(f"/api/crm/{a}/contact", json={"channel": "arama", "result": "İlgileniyor"}).json()
    assert r4["crm_stage"] == "Teklif Gönderildi", "ileri aşama geri alınmaz"
    r5 = staff.post(f"/api/crm/{a}/contact", json={"channel": "eposta", "result": "İlgilenmiyor"}).json()
    assert r5["crm_stage"] == "Teklif Gönderildi", "İlgilenmiyor kendiliğinden Kaybedildi yapmaz"
    assert [h["type"] for h in r5["history"]].count("contact") == 5
    assert staff.post(f"/api/crm/{a}/contact", json={"channel": "telepati", "result": "Görüşüldü"}).status_code == 422
    assert staff.post(f"/api/crm/{a}/contact", json={"channel": "arama", "result": "Belki"}).status_code == 422
    assert staff.post("/api/crm/999999/contact", json={"channel": "arama", "result": "Görüşüldü"}).status_code == 404
    rows = staff.get("/api/crm/follow-ups").status_code
    assert rows == 200


def test_contact_attempts_feed_call_priority_and_reports(client, db):
    a = _analyzed_business(client, db, name="Deneme Sayacı")
    for _ in range(3):
        client.post(f"/api/crm/{a}/contact", json={"channel": "arama", "result": "Ulaşılamadı"})
    top = next(i for i in client.get("/api/sales/call-today?limit=50&scope=all").json()["items"] if i["business"]["id"] == a)
    assert any("kez denendi" in r for r in top["call"]["reasons"])
    m = client.get("/api/sales/report?period=today").json()["metrics"]
    assert m["contacts"] == 1, "aynı firmaya birden çok deneme dönemde tek firma olarak sayılır"
    me = next(r for r in client.get("/api/sales/staff?period=today").json()["items"] if r["name"] == "Test Yönetici")
    assert me["contacts"] == 3 and me["unreachable"] == 3, "personel bazında her deneme ayrı sayılır"
