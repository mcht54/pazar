"""Seed data: Türkiye'nin 81 ili + tüm ilçeleri (statik veri dosyasından), 55+ sektör
(OpenStreetMap etiketleri + Türkçe anahtar kelimelerle), Mchttasarım hizmet kataloğu,
integrations_registry.

Run with: python -m packages.db.seed
Idempotent: safe to re-run (var olan kayıtları isim/natural-key ile günceller, yenilerini ekler).

İl/ilçe verisi packages/db/data/turkey_locations.json dosyasında statik olarak tutulur —
uygulama çalışırken bu veri hiçbir zaman internetten aranmaz. Kaynak: TürkiyeAPI (2025
resmi il/ilçe listesi, https://turkiyeapi.dev) + ilçe koordinatları OpenStreetMap Nominatim
ile tek seferlik geocode edilmiştir (bkz. dosyadaki `geocode_source` alanı).
"""

import json
import math
from datetime import date
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from packages.db.base import SessionLocal
from packages.db.models import Region, Sector, IntegrationRegistry, ServiceCatalog, Business

MIN_IL_RADIUS_M = 8000
MAX_IL_RADIUS_M = 25000
MIN_ILCE_RADIUS_M = 4000
MAX_ILCE_RADIUS_M = 12000


def _radius_from_area(area_km2: float | None, min_r: int, max_r: int) -> int:
    """Bölgenin gerçek yüzölçümünden (varsa) makul bir arama yarıçapı türetir —
    sabit/uydurma bir değer yerine gerçek veriye dayalı, ama Overpass/Google sorgu
    maliyetini kontrol altında tutmak için sınırlanmış bir yarıçap."""
    if not area_km2:
        return min_r
    radius_m = math.sqrt(area_km2 / math.pi) * 1000
    return int(max(min_r, min(max_r, radius_m)))


def _load_turkey_locations() -> dict:
    path = Path(__file__).parent / "data" / "turkey_locations.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _seed_regions(db) -> None:
    data = _load_turkey_locations()
    province_region_id_by_external_id: dict[int, int] = {}

    for p in data["provinces"]:
        radius = _radius_from_area(p.get("area_km2"), MIN_IL_RADIUS_M, MAX_IL_RADIUS_M)
        region = db.query(Region).filter_by(name=p["name"], level="il").one_or_none()
        if region is None:
            region = Region(name=p["name"], level="il", center_lat=p["lat"], center_lng=p["lng"], search_radius_m=radius)
            db.add(region)
            db.flush()
        else:
            region.center_lat = p["lat"]
            region.center_lng = p["lng"]
            region.search_radius_m = radius
        province_region_id_by_external_id[p["id"]] = region.id

    for d in data["districts"]:
        parent_id = province_region_id_by_external_id[d["provinceId"]]
        radius = _radius_from_area(d.get("area_km2"), MIN_ILCE_RADIUS_M, MAX_ILCE_RADIUS_M)
        # Doğal anahtar (name, parent_region_id) — Türkiye'de bazı ilçe isimleri
        # farklı illerde tekrar edebildiği için (ör. Yenişehir) sadece isme göre
        # arama yanlış eşleşmeye/çakışmaya yol açar.
        region = (
            db.query(Region)
            .filter_by(name=d["name"], level="ilce", parent_region_id=parent_id)
            .one_or_none()
        )
        if region is None:
            db.add(
                Region(
                    name=d["name"],
                    level="ilce",
                    parent_region_id=parent_id,
                    center_lat=d["lat"],
                    center_lng=d["lng"],
                    search_radius_m=radius,
                )
            )
        else:
            region.center_lat = d["lat"]
            region.center_lng = d["lng"]
            region.search_radius_m = radius
    db.flush()

# name, osm_tags ("key=value" — OverpassProvider bunu doğrudan sorguya çevirir), keyword_variants
# Not: OSM etiket kapsamı sektöre ve bölgeye göre değişir; bu yüzden her sektöre isim bazlı
# (regex) bir yedek arama da eklenmiştir. Bazı B2B sektörlerde (ör. nakliyat, kargo) OSM
# kapsamı zayıf olabilir — bu bir uygulama hatası değil, kaynağın doğal bir sınırıdır.
SECTORS = [
    ("Restoran", ["amenity=restaurant"], ["restoran", "lokanta"]),
    ("Kafe", ["amenity=cafe"], ["kafe", "cafe"]),
    ("Fast Food", ["amenity=fast_food"], ["fast food", "büfe"]),
    ("Pastane", ["shop=pastry", "shop=confectionery"], ["pastane", "tatlıcı"]),
    ("Fırın", ["shop=bakery"], ["fırın", "unlu mamül"]),
    ("Diş Kliniği", ["amenity=dentist"], ["diş kliniği", "diş hekimi", "ağız ve diş"]),
    ("Özel Klinik", ["amenity=clinic"], ["özel klinik", "poliklinik", "tıp merkezi"]),
    ("Güzellik Salonu", ["shop=beauty"], ["güzellik salonu", "güzellik merkezi", "estetik"]),
    ("Kuaför", ["shop=hairdresser"], ["kuaför"]),
    ("Berber", ["shop=hairdresser"], ["berber", "erkek kuaförü"]),
    ("Emlak", ["office=estate_agent"], ["emlak", "emlakçı", "gayrimenkul"]),
    ("İnşaat", ["office=construction_company"], ["inşaat", "müteahhit", "yapı"]),
    ("Mimarlık", ["office=architect"], ["mimarlık", "mimar"]),
    ("Mühendislik", ["office=engineer"], ["mühendislik", "müşavirlik"]),
    ("Mobilya", ["shop=furniture"], ["mobilya", "mobilyacı"]),
    ("Mutfak", ["shop=kitchen"], ["mutfak dolabı", "mutfak"]),
    ("Beyaz Eşya", ["shop=appliance"], ["beyaz eşya"]),
    ("Elektronik", ["shop=electronics"], ["elektronik"]),
    ("Telefon Mağazası", ["shop=mobile_phone"], ["cep telefonu", "telefon mağazası", "gsm"]),
    ("Oto Galeri", ["shop=car"], ["oto galeri", "ikinci el araç", "galeri"]),
    ("Oto Servis", ["shop=car_repair"], ["oto servis", "oto tamir", "yetkili servis"]),
    ("Oto Yıkama", ["shop=car_wash", "amenity=car_wash"], ["oto yıkama"]),
    ("Lastikçi", ["shop=tyres"], ["lastikçi", "lastik"]),
    ("Sigorta", ["office=insurance"], ["sigorta", "sigorta acentesi"]),
    ("Finans", ["office=financial", "amenity=bank"], ["finansman", "banka"]),
    ("Hukuk Bürosu", ["office=lawyer"], ["hukuk bürosu", "avukat", "avukatlık"]),
    ("Muhasebe", ["office=accountant"], ["muhasebe", "mali müşavir", "smmm"]),
    ("Nakliyat", ["office=moving_company"], ["nakliyat", "nakliye", "evden eve", "taşımacılık"]),
    ("Kargo", ["shop=courier", "office=courier"], ["kargo"]),
    ("Matbaa", ["shop=copyshop", "craft=printer"], ["matbaa", "baskı", "dijital baskı"]),
    ("Reklam Ajansı", ["office=advertising_agency"], ["reklam ajansı", "reklam"]),
    ("Web Tasarım", ["office=it"], ["web tasarım", "web tasarımı", "internet sitesi"]),
    ("Yazılım", ["office=it"], ["yazılım", "software", "bilgisayar programcılığı"]),
    ("Fotoğrafçı", ["shop=photo", "craft=photographer"], ["fotoğrafçı", "fotoğraf stüdyosu"]),
    ("Düğün Salonu", ["amenity=events_venue", "amenity=wedding_hall"], ["düğün salonu", "davet salonu"]),
    ("Organizasyon", ["office=event_management"], ["organizasyon", "etkinlik", "organizasyon firması"]),
    ("Otel", ["tourism=hotel"], ["otel", "hotel"]),
    ("Bungalov", ["tourism=chalet"], ["bungalov", "tatil köyü"]),
    ("Spor Salonu", ["leisure=fitness_centre"], ["spor salonu", "fitness", "gym"]),
    ("Veteriner", ["amenity=veterinary"], ["veteriner", "veteriner kliniği"]),
    ("Pet Shop", ["shop=pet"], ["pet shop", "evcil hayvan"]),
    ("Market", ["shop=supermarket", "shop=convenience"], ["market", "süpermarket"]),
    ("Giyim Mağazası", ["shop=clothes"], ["giyim", "tekstil mağazası", "butik"]),
    ("Ayakkabı Mağazası", ["shop=shoes"], ["ayakkabı", "ayakkabıcı"]),
    ("Çiçekçi", ["shop=florist"], ["çiçekçi", "çiçek"]),
    ("Hırdavat", ["shop=hardware"], ["hırdavat", "nalbur"]),
    ("Yapı Malzemeleri", ["shop=doityourself", "shop=trade"], ["yapı market", "yapı malzemeleri", "inşaat malzemeleri"]),
    ("Plywood / Kontrplak", ["shop=trade"], ["kontrplak", "plywood", "ahşap levha", "sunta"]),
    ("Perde / Tekstil", ["shop=curtain", "shop=houseware"], ["perde", "ev tekstili"]),
    ("Eğitim / Kurs", ["office=educational_institution", "amenity=driving_school"], ["kurs", "eğitim merkezi", "dershane", "sürücü kursu"]),
    ("Eczane", ["amenity=pharmacy"], ["eczane"]),
    ("Optik", ["shop=optician"], ["optik", "gözlükçü"]),
    ("Halı Yıkama", ["shop=laundry", "craft=carpet_cleaner"], ["halı yıkama"]),
    ("Temizlik Şirketi", ["office=cleaning"], ["temizlik şirketi", "temizlik firması"]),
    ("Kırtasiye", ["shop=stationery"], ["kırtasiye"]),
]

OBSOLETE_SECTOR_NAMES = [
    "Web Tasarım İhtiyacı Olabilecek Tüm İşletmeler",
    "Kuaför / Güzellik Salonu",
    "Otomotiv Servisi",
]

SERVICES = [
    # service_name, description, target_sectors([] = hepsi), sales_arguments, deliverables
    (
        "Web Tasarım",
        "Kurumsal/tanıtım web sitesi tasarımı ve geliştirmesi.",
        [],
        ["Web sitesi olmayan işletmeler aramalarda ve sosyal medya bio linklerinde görünmez.",
         "Mevcut siteye erişilemiyorsa müşteri kaybı riski var."],
        ["Responsive web sitesi", "İletişim/CTA entegrasyonu", "Temel SEO altyapısı"],
    ),
    (
        "E-ticaret Sitesi",
        "Online satış yapılabilen e-ticaret altyapısı kurulumu.",
        [],
        ["Ürün/hizmet satışını dijitale taşımak isteyen işletmeler için."],
        ["E-ticaret sitesi", "Ödeme entegrasyonu", "Ürün kataloğu"],
    ),
    (
        "SEO",
        "Arama motoru optimizasyonu — on-page ve teknik SEO iyileştirmeleri.",
        [],
        ["Meta description/H1/schema gibi temel SEO sinyalleri eksikse arama görünürlüğü düşer."],
        ["On-page SEO denetimi", "Meta etiket optimizasyonu", "Yapılandırılmış veri (schema) ekleme"],
    ),
    (
        "Google Ads",
        "Google arama/görüntülü reklam kampanyaları.",
        [],
        ["Ticari niyeti yüksek aramalarda rakiplerin reklam verdiği sektörlerde görünürlük sağlar."],
        ["Kampanya taslağı", "Anahtar kelime araştırması", "Reklam metni"],
    ),
    (
        "Sosyal Medya Yönetimi",
        "Instagram/Facebook içerik planlama ve yönetimi.",
        [],
        ["Sosyal medya hesabına ulaşılamıyor veya düzensizse marka bilinirliği zayıf kalır."],
        ["Aylık içerik planı", "Görsel/metin üretimi", "Paylaşım takvimi"],
    ),
    (
        "Google Business Optimizasyonu",
        "Google Business Profili eksiklerinin giderilmesi (fotoğraf, açıklama, yorum yönetimi).",
        [],
        ["Düşük yorum sayısı veya az fotoğraf, Google Haritalar'da rekabeti zayıflatır."],
        ["Profil düzenleme", "Fotoğraf yükleme", "Yorum yönetimi süreci"],
    ),
    (
        "Grafik Tasarım",
        "Kurumsal kimlik, sosyal medya ve baskı görselleri tasarımı.",
        [],
        ["Az sayıda/eski görsel varlık, dijital ve fiziksel iletişimde profesyonellik algısını zayıflatır."],
        ["Logo/kurumsal kimlik", "Sosyal medya görselleri", "Baskı tasarımları"],
    ),
    (
        "Matbaa",
        "Kartvizit, broşür, katalog gibi baskı ürünleri.",
        [],
        ["Fiziksel tanıtım materyaline ihtiyaç duyan işletmeler için."],
        ["Kartvizit", "Broşür/katalog baskısı"],
    ),
    (
        "Branda Baskı",
        "Tabela, branda ve büyük format baskı uygulamaları.",
        [],
        ["Fiziksel mekan tanıtımı için görsel materyal ihtiyacı olan işletmeler için."],
        ["Branda baskı ve montaj"],
    ),
    (
        "Promosyon Ürünleri",
        "Marka logolu promosyon/hediyelik ürün üretimi.",
        [],
        ["Müşteri sadakati ve marka bilinirliği için promosyon ürünleri."],
        ["Promosyon ürün tasarımı ve üretimi"],
    ),
    (
        "Tabela ve Reklam Uygulamaları",
        "İşletme tabelası ve dış mekan reklam uygulamaları.",
        [],
        ["Fiziksel görünürlüğü zayıf işletmeler için tabela/dış mekan reklamı."],
        ["Tabela tasarımı ve uygulaması"],
    ),
]

INTEGRATIONS = [
    dict(
        name="openstreetmap_overpass",
        terms_url="https://operations.osmfoundation.org/policies/overpass/",
        quota_config={
            "note": "Sabit bir günlük kota yok; fair-use politikası — istek başına makul aralık ve timeout uygulanır.",
            "min_interval_seconds": 2,
        },
        cache_policy={
            "note": "Aynı bölge+sektör için yeterli işletme zaten DB'de varsa tekrar sorgu atılmaz (bkz. discovery task).",
        },
        requires_oauth=False,
        attribution_requirements="© OpenStreetMap contributors — ODbL lisansı gereği veri gösterilen ekranlarda attribution zorunlu.",
        last_reviewed_at=date(2026, 9, 18),
    ),
    dict(
        name="google_places",
        terms_url="https://cloud.google.com/maps-platform/terms",
        quota_config={
            "daily_request_cap": 200,
            "unit": "requests/day",
            "configurable": True,
            "note": "Text Search (New) çoğu istenen alan (rating, telefon, website, saat) Enterprise SKU'ya girer — kota düşük tutulmalı, sadece kullanıcı 'Analiz Et'/discovery tetiklediğinde çağrılır.",
        },
        cache_policy={
            "note": "Google Places ToS'a göre alan bazlı cache süresi değişebilir; sabit varsayım yapılmaz.",
            "default_ttl_days": None,
            "requires_manual_review_before_prod": True,
        },
        requires_oauth=False,
        attribution_requirements="Places verisi gösterilen ekranlarda 'Powered by Google' / Google logosu attribution'ı gösterilmeli.",
        last_reviewed_at=date(2026, 9, 18),
    ),
    dict(
        name="google_pagespeed",
        terms_url="https://developers.google.com/speed/docs/insights/v5/about",
        quota_config={"daily_request_cap": 25000, "unit": "requests/day"},
        cache_policy={"default_ttl_days": 7},
        requires_oauth=False,
        attribution_requirements=None,
        last_reviewed_at=date(2026, 9, 18),
    ),
    dict(
        name="anthropic_claude",
        terms_url="https://www.anthropic.com/legal/commercial-terms",
        quota_config={"note": "Kota, kullanılan API planına göre değişir; api_usage_ledger üzerinden izlenir."},
        cache_policy={"default_ttl_days": None},
        requires_oauth=False,
        attribution_requirements=None,
        last_reviewed_at=date(2026, 9, 18),
    ),
]


def run():
    db = SessionLocal()
    try:
        _seed_regions(db)

        for name, osm_tags, keywords in SECTORS:
            sector = db.query(Sector).filter_by(name=name).one_or_none()
            if sector is None:
                db.add(Sector(name=name, google_place_types=osm_tags, keyword_variants=keywords))
            else:
                sector.google_place_types = osm_tags
                sector.keyword_variants = keywords

        for obsolete_name in OBSOLETE_SECTOR_NAMES:
            sector = db.query(Sector).filter_by(name=obsolete_name).one_or_none()
            if sector is None:
                continue
            in_use = db.query(Business).filter_by(sector_id=sector.id).first() is not None
            if in_use:
                print(f"Uyarı: '{obsolete_name}' sektörü işletmeler tarafından kullanıldığı için silinmedi.")
                continue
            db.delete(sector)

        for service_name, description, target_sectors, sales_arguments, deliverables in SERVICES:
            service = db.query(ServiceCatalog).filter_by(service_name=service_name).one_or_none()
            if service is None:
                db.add(
                    ServiceCatalog(
                        service_name=service_name,
                        description=description,
                        target_sectors=target_sectors,
                        required_signals={},
                        opportunity_rules={},
                        sales_arguments=sales_arguments,
                        deliverables=deliverables,
                    )
                )

        for integration in INTEGRATIONS:
            stmt = pg_insert(IntegrationRegistry).values(**integration)
            stmt = stmt.on_conflict_do_update(index_elements=["name"], set_=integration)
            db.execute(stmt)

        db.commit()
        region_count = db.query(Region).count()
        print(
            f"Seed OK: {region_count} region (81 il + ilçeler), {len(SECTORS)} sector, "
            f"{len(SERVICES)} service, {len(INTEGRATIONS)} integration_registry kaydı."
        )
    except IntegrityError:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
