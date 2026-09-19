"""Sektör listesi (Türkçe, ≥50, İşitme Cihazı Merkezi dahil), yerinde yeniden adlandırma ve yerelleştirme yardımcıları."""

import re

from packages.db.models import Business, Region, Sector
from packages.db.sectors_data import SECTOR_RENAMES, SECTORS
from packages.localization import contains_phrase, fold, normalize_host, tr_capitalize_first

ENGLISH_ONLY_NAMES = ["Fast Food", "Pet Shop", "Plywood", "Restaurant", "Hotel ", "Clinic", "Salon Beauty"]


def test_at_least_50_sectors_and_hearing_aid_center_present():
    names = [s[0] for s in SECTORS]
    assert len(names) >= 50
    assert len(names) == len(set(names)), "sektör adları tekil olmalı"
    assert "İşitme Cihazı Merkezi" in names
    terms = next(s for s in SECTORS if s[0] == "İşitme Cihazı Merkezi")[2]
    assert terms[0] == "işitme cihazı", "Google Haritalar'da aranacak birincil ifade sektörü doğru anlatmalı"


def test_every_sector_is_searchable_and_grouped():
    for name, group, terms in SECTORS:
        assert group, f"{name}: grup yok"
        assert terms, f"{name}: arama ifadesi yok — seçilse bile Google Haritalar'da aranamaz"
        assert all(t == t.strip() and t for t in terms)


def test_sector_names_are_turkish():
    names = [s[0] for s in SECTORS]
    for bad in ENGLISH_ONLY_NAMES:
        assert not any(bad.strip() == n or n.startswith(bad) for n in names), f"İngilizce sektör adı kalmış: {bad}"


def test_seed_makes_all_sectors_selectable(seeded_db):
    active = seeded_db.query(Sector).filter(Sector.is_active.is_(True)).all()
    assert len(active) == len(SECTORS)
    assert all(s.group_name for s in active)


def test_seed_is_idempotent(seeded_db):
    from packages.db import seed as seed_module

    before = seeded_db.query(Sector).count()
    seed_module.run()
    seeded_db.expire_all()
    assert seeded_db.query(Sector).count() == before


def test_renaming_old_english_sector_keeps_its_businesses(db):
    from packages.db import seed as seed_module

    seed_module._seed_regions(db)
    region = db.query(Region).filter_by(name="Serdivan").one()
    old = Sector(name="Fast Food", google_place_types=[], keyword_variants=["büfe"])
    db.add(old)
    db.flush()
    business = Business(name="Eski Büfe", sector_id=old.id, region_id=region.id, google_place_id="gmaps_1", discovery_source="google_maps")
    db.add(business)
    db.commit()
    old_id = old.id

    seed_module.run()
    db.expire_all()

    renamed = db.get(Sector, old_id)
    assert renamed.name == SECTOR_RENAMES["Fast Food"] == "Hızlı Yemek / Büfe"
    assert db.get(Business, business.id).sector_id == old_id, "işletme yeni ada taşınan aynı sektöre bağlı kalmalı"
    assert db.query(Sector).filter_by(name="Fast Food").count() == 0


def test_obsolete_sector_in_use_is_deactivated_not_deleted(db):
    from packages.db import seed as seed_module

    seed_module._seed_regions(db)
    region = db.query(Region).filter_by(name="Serdivan").one()
    obsolete = Sector(name="Yazılım", google_place_types=[], keyword_variants=["yazılım"])
    db.add(obsolete)
    db.flush()
    db.add(Business(name="Yazılımcı", sector_id=obsolete.id, region_id=region.id, google_place_id="gmaps_2", discovery_source="google_maps"))
    db.commit()

    seed_module.run()
    db.expire_all()
    row = db.query(Sector).filter_by(name="Yazılım").one()
    assert row.is_active is False


def test_sectors_api_lists_only_active_and_has_groups(client):
    data = client.get("/api/sectors").json()
    names = {s["name"] for s in data}
    assert len(data) >= 50
    assert "İşitme Cihazı Merkezi" in names
    assert all(s["group_name"] for s in data)


# ---------------------------------------------------------------- yerelleştirme
def test_fold_handles_turkish_case_and_diacritics():
    assert fold("ADAPAZARI") == fold("Adapazarı") == fold("adapazari") == "adapazari"
    assert fold("İşitme Cihazı") == "isitme cihazi"
    assert contains_phrase("Sakarya'da işitme cihazı merkezi", "İŞİTME CİHAZI")


def test_normalize_host_unifies_variants():
    assert normalize_host("https://www.JavaRestaurant.tr/") == normalize_host("javarestaurant.tr") == "javarestaurant.tr"
    assert normalize_host("http://a.com/x?y=1") == "a.com"
    assert normalize_host("") is None and normalize_host(None) is None


def test_turkish_capitalization_of_first_letter():
    assert tr_capitalize_first("iletişim noktası") == "İletişim noktası"
    assert tr_capitalize_first("ısı yalıtımı") == "Isı yalıtımı"
    assert tr_capitalize_first("web sitesi") == "Web sitesi"
    assert tr_capitalize_first("") == ""
