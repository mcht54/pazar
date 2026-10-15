"""MarkaKarnem aday akışı: anahtarsız kapalı, yanlış anahtar 401; CRM'deki firmalar ve rakip ajanslar listeye girmez; iç alanlar verilmez."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.api.main import app
from packages.config import settings
from packages.db.models import Business, Region, Sector


def _biz(db, name, reviews, rating=4.6, **kw):
    region = db.query(Region).filter_by(name="Serdivan").one()
    sector = db.query(Sector).filter_by(name="İşitme Cihazı Merkezi").one()
    b = Business(name=name, sector_id=sector.id, region_id=region.id, google_place_id=f"p_{name}", discovery_source="google_places", status="analyzed",
                 google_review_count=reviews, google_rating=rating, phone="0532 111 22 33", email="gizli@ornek.com", staff_note="iç not", **kw)
    db.add(b)
    db.commit()
    return b


def test_feed_is_closed_without_token_and_filters_crm_and_agencies(seeded_db, monkeypatch):
    db = seeded_db
    c = TestClient(app)
    monkeypatch.setattr(settings, "karne_feed_token", "")
    assert c.get("/api/feed/karne-candidates").status_code == 404, "anahtar tanımlı değilse uç yok"
    monkeypatch.setattr(settings, "karne_feed_token", "t" * 40)
    assert c.get("/api/feed/karne-candidates", headers={"X-Feed-Token": "yanlis"}).status_code == 401
    _biz(db, "Çok Yorumlu", 300)
    _biz(db, "Az Yorumlu", 10)
    _biz(db, "Düşük Puanlı", 300, rating=3.2)
    _biz(db, "CRM'deki Müşteri", 400, crm_added_at=datetime.now(timezone.utc), crm_stage="Kazanıldı")
    _biz(db, "Sakarya Reklam Ajansı", 500)
    r = c.get("/api/feed/karne-candidates", headers={"X-Feed-Token": "t" * 40})
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["name"] for i in items] == ["Çok Yorumlu"]
    assert items[0]["il"] == "Sakarya" and items[0]["ilce"] == "Serdivan" and items[0]["sector"] == "İşitme Cihazı Merkezi"
    assert "gizli@ornek.com" not in r.text and "iç not" not in r.text, "e-posta ve personel notu verilmez"
