"""CRM durum listesi (9 aşama): backend doğrulaması, API, liste/sayaçlar ve eski kayıtların migration ile dönüşümü."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from packages.crm import CRM_STAGES
from packages.db.models import Business, CrmActivity

from tests.test_crm_and_reports import _make_business
from tests.test_sales_features import _analyzed_business

NINE = ["Yeni", "Aranacak", "Daha Sonra Ara", "Arandı", "Görüşüldü", "Teklif Gönderildi", "Takip Bekliyor", "Kazanıldı", "Kaybedildi"]


def test_every_stage_can_be_set_in_sequence_without_invalid_status_error(client, db):
    bid = _analyzed_business(client, db, name="Yaşam Döngüsü Firması")
    assert client.get(f"/api/businesses/{bid}").json()["business"]["crm_stage"] == "Yeni"
    r = client.post(f"/api/businesses/{bid}/crm", json={"stage": "Yeni"})
    assert r.status_code == 200 and r.json()["crm_stage"] == "Yeni", "yeni lead oluşturuldu"
    for stage in NINE[1:]:
        r = client.patch(f"/api/businesses/{bid}/crm", json={"stage": stage})
        assert r.status_code == 200, (stage, r.text)
        assert "Geçersiz CRM durumu" not in r.text and r.json()["crm_stage"] == stage
        assert client.get(f"/api/businesses/{bid}").json()["business"]["crm_stage"] == stage
        assert client.get(f"/api/crm?stage={stage}").status_code == 200
    hist = [h["to_stage"] for h in client.get(f"/api/businesses/{bid}").json()["crm_history"]]
    assert hist[::-1] == NINE, "her aşama geçmişe sırayla işlendi"
    listing = client.get("/api/crm").json()
    assert list(listing["counts"]) == NINE and listing["counts"]["Kaybedildi"] == 1 and sum(listing["counts"].values()) == 1
    summary = client.get("/api/crm/summary").json()
    assert set(summary["by_stage"]) == set(NINE)


def test_validation_message_lists_only_the_nine_new_stages(client, db):
    bid = _analyzed_business(client, db, name="Hata Mesajı")
    r = client.post(f"/api/businesses/{bid}/crm", json={"stage": "Olumsuz"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Geçersiz CRM durumu. Geçerli durumlar: " + ", ".join(NINE)
    assert CRM_STAGES == NINE
    assert client.get("/api/crm/meta").json()["stages"] == NINE


def test_nine_stage_migration_converts_old_names_and_restores_merged_ones(seeded_db):
    """e6f0a4b8c334: eski adlar dönüştürülür; 7 aşamalı ara sürümde birleşen kayıtlar legacy_stage ile özgün adına döner; kayıt silinmez; downgrade çalışır."""
    path = next(Path(__file__).resolve().parent.parent.glob("packages/db/migrations/versions/*crm_nine_stages.py"))
    spec = importlib.util.spec_from_file_location("nine_stage_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = seeded_db

    def make(name, stage, legacy=None):
        b = _make_business(db, name)
        db.execute(text("UPDATE businesses SET crm_stage=:s, crm_added_at=now(), crm_last_action=:a WHERE id=:i"), {"s": stage, "i": b.id, "a": f"{stage} → {stage}"})
        db.add(CrmActivity(business_id=b.id, type="status_change", from_stage="Yeni Lead", to_stage=stage, note=name, meta={"legacy_stage": legacy} if legacy else None))
        return b.id

    ids = {
        # 7 aşamalı ara sürümden (özgün adı meta'da)
        "gorusuldu": make("g", "İletişime Geçildi", "Görüşüldü"), "aranacak": make("a", "Yeni Lead", "Aranacak"), "sonra": make("s", "Takip Bekliyor", "Daha Sonra Ara"),
        "arandi": make("r", "İletişime Geçildi", "Arandı"), "ulasilamadi": make("u", "İletişime Geçildi", "Ulaşılamadı"),
        # özgün adı olmayan ara sürüm kayıtları
        "lead": make("l", "Yeni Lead"), "ilgi": make("i", "İlgileniyor"),
        # ilk sürümün eski adları
        "verildi": make("v", "Teklif Verildi"), "takipte": make("t", "Takipte"), "musteri": make("m", "Müşteri Oldu"), "olumsuz": make("o", "Olumsuz"),
    }
    db.commit()
    total = db.query(CrmActivity).count()
    with Operations.context(MigrationContext.configure(db.connection())):
        module.upgrade()
    db.commit()
    db.expire_all()
    stage = lambda k: db.get(Business, ids[k]).crm_stage
    assert (stage("gorusuldu"), stage("aranacak"), stage("sonra"), stage("arandi")) == ("Görüşüldü", "Aranacak", "Daha Sonra Ara", "Arandı"), "birleşen kayıtlar özgün adına döndü"
    assert stage("ulasilamadi") == "Arandı" and stage("lead") == "Yeni" and stage("ilgi") == "Görüşüldü"
    assert (stage("verildi"), stage("takipte"), stage("musteri"), stage("olumsuz")) == ("Teklif Gönderildi", "Takip Bekliyor", "Kazanıldı", "Kaybedildi")
    assert {r[0] for r in db.execute(text("SELECT crm_stage FROM businesses"))} <= set(NINE)
    assert {r[0] for r in db.execute(text("SELECT to_stage FROM crm_activities"))} <= set(NINE)
    assert db.query(CrmActivity).count() == total, "hiçbir kayıt silinmedi"
    leftover = [a.meta["legacy_stage"] for a in db.query(CrmActivity).all() if "legacy_stage" in (a.meta or {})]
    assert leftover == ["Ulaşılamadı"], "geri getirilenlerin geçici meta anahtarı temizlendi; yeni listede karşılığı olmayan eski ad ('Ulaşılamadı') tarihçe olarak kalır"
    with Operations.context(MigrationContext.configure(db.connection())):
        module.downgrade()
    db.commit()
    db.expire_all()
    assert stage("gorusuldu") == "İlgileniyor" and stage("aranacak") == "Yeni Lead" and stage("arandi") == "İletişime Geçildi", "downgrade 7 aşamalı sürüme döner"
