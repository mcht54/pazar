"""Seed data: regions (6 şehir + Sakarya'nın 16 ilçesi), 50+ sektör (OpenStreetMap
etiketleri + Türkçe anahtar kelimelerle), Mchttasarım hizmet kataloğu, integrations_registry.

Run with: python -m packages.db.seed
Idempotent: safe to re-run (var olan kayıtları isim/natural-key ile günceller, yenilerini ekler).
"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from packages.db.base import SessionLocal
from packages.db.models import Region, Sector, IntegrationRegistry, ServiceCatalog, Business

REGIONS = [
    # name, level, parent_name, center_lat, center_lng, search_radius_m
    ("Sakarya", "il", None, 40.7569, 30.3781, 20000),
    ("Kocaeli", "il", None, 40.7654, 29.9408, 20000),
    ("İstanbul", "il", None, 41.0082, 28.9784, 25000),
    ("Bursa", "il", None, 40.1826, 29.0665, 20000),
    ("Ankara", "il", None, 39.9334, 32.8597, 20000),
    ("İzmir", "il", None, 38.4237, 27.1428, 20000),
    # Sakarya ilçeleri — koordinatlar ilçe merkezine yakın kabul edilir; search_radius_m
    # bu yaklaşıklığı telafi edecek şekilde seçilmiştir.
    ("Adapazarı", "ilce", "Sakarya", 40.7815, 30.4028, 8000),
    ("Serdivan", "ilce", "Sakarya", 40.7627, 30.3399, 7000),
    ("Erenler", "ilce", "Sakarya", 40.7423, 30.4212, 7000),
    ("Arifiye", "ilce", "Sakarya", 40.6959, 30.3702, 6000),
    ("Sapanca", "ilce", "Sakarya", 40.6900, 30.2650, 8000),
    ("Hendek", "ilce", "Sakarya", 40.7986, 30.7444, 7000),
    ("Akyazı", "ilce", "Sakarya", 40.6845, 30.6221, 7000),
    ("Geyve", "ilce", "Sakarya", 40.5119, 30.2882, 7000),
    ("Pamukova", "ilce", "Sakarya", 40.5000, 30.1500, 6000),
    ("Karasu", "ilce", "Sakarya", 41.1077, 30.6884, 8000),
    ("Kocaali", "ilce", "Sakarya", 41.0450, 30.8547, 6000),
    ("Ferizli", "ilce", "Sakarya", 40.9247, 30.5364, 5000),
    ("Kaynarca", "ilce", "Sakarya", 41.0450, 30.3050, 6000),
    ("Söğütlü", "ilce", "Sakarya", 40.8747, 30.4972, 5000),
    ("Karapürçek", "ilce", "Sakarya", 40.6333, 30.4833, 5000),
    ("Taraklı", "ilce", "Sakarya", 40.3833, 30.4833, 6000),
]

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
        quota_config={"daily_request_cap": 1000, "unit": "requests/day", "configurable": True},
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
        region_ids_by_name: dict[str, int] = {}
        for name, level, parent_name, lat, lng, radius in REGIONS:
            region = db.query(Region).filter_by(name=name).one_or_none()
            if region is None:
                region = Region(name=name, level=level, center_lat=lat, center_lng=lng, search_radius_m=radius)
                db.add(region)
                db.flush()
            else:
                region.level = level
                region.center_lat = lat
                region.center_lng = lng
                region.search_radius_m = radius
            region_ids_by_name[name] = region.id

        for name, level, parent_name, *_ in REGIONS:
            if parent_name:
                region = db.query(Region).filter_by(name=name).one()
                region.parent_region_id = region_ids_by_name[parent_name]

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
        print(
            f"Seed OK: {len(REGIONS)} region, {len(SECTORS)} sector, {len(SERVICES)} service, "
            f"{len(INTEGRATIONS)} integration_registry kaydı."
        )
    except IntegrityError:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
