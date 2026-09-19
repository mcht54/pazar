"""Seed data: Türkiye'nin 81 ili + tüm ilçeleri (statik veri dosyasından), 100+ Türkçe sektör
(packages/db/sectors_data.py — Türkçe arama ifadeleriyle),
Mchttasarım hizmet kataloğu, integrations_registry.

Run with: python -m packages.db.seed
Idempotent: safe to re-run (var olan kayıtları isim/natural-key ile günceller, yenilerini ekler).

İl/ilçe verisi packages/db/data/turkey_locations.json dosyasında statik olarak tutulur —
uygulama çalışırken bu veri hiçbir zaman internetten aranmaz. Kaynak: TürkiyeAPI (2025
resmi il/ilçe listesi, https://turkiyeapi.dev) + ilçe koordinatları Nominatim
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
from packages.db.sectors_data import OBSOLETE_SECTOR_NAMES, SECTOR_RENAMES, SECTORS

MIN_IL_RADIUS_M = 8000
MAX_IL_RADIUS_M = 25000
MIN_ILCE_RADIUS_M = 4000
MAX_ILCE_RADIUS_M = 12000


def _radius_from_area(area_km2: float | None, min_r: int, max_r: int) -> int:
    """Bölgenin gerçek yüzölçümünden (varsa) makul bir arama yarıçapı türetir —
    sabit/uydurma bir değer yerine gerçek veriye dayalı, ama Google Haritalar sorgu
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

# Mchttasarım'ın satabildiği 12 hizmet. Eski/İngilizce adlar SERVICE_RENAMES ile yerinde yeniden adlandırılır.
SERVICE_RENAMES = {
    "SEO": "Kurumsal SEO",
    "Google Business Optimizasyonu": "Google İşletme Profili Optimizasyonu",
    "E-ticaret Sitesi": "E-Ticaret",
    "Tabela ve Reklam Uygulamaları": "Tabela",
}

SERVICES = [
    # service_name, description, target_sectors([] = hepsi), sales_arguments, deliverables
    (
        "Web Tasarım",
        "Mevcut web sitesinin mobil uyumlu, hızlı ve dönüşüm odaklı olarak yeniden tasarlanması.",
        [],
        ["Site var ama mobil kullanım, iletişim noktaları veya güven unsurları zayıfsa ziyaretçi iletişime geçmeden ayrılır."],
        ["Mobil uyumlu yeni tasarım", "İletişim/WhatsApp/telefon entegrasyonu", "Hız ve güvenlik iyileştirmesi"],
    ),
    (
        "Kurumsal Web Sitesi",
        "Web sitesi olmayan işletmeler için sıfırdan kurumsal web sitesi kurulumu.",
        [],
        ["Web sitesi olmayan işletme, Google'da arama yapan müşteriye dijital olarak ulaşılamaz durumdadır."],
        ["Kurumsal web sitesi", "Hizmet/hakkımızda/iletişim sayfaları", "Temel yerel SEO altyapısı"],
    ),
    (
        "E-Ticaret",
        "Online satış yapılabilen e-ticaret altyapısı kurulumu.",
        [],
        ["Ürün satan ama online satış kanalı olmayan işletme, mağaza dışındaki talebi kaçırır."],
        ["E-ticaret sitesi", "Ödeme ve kargo entegrasyonu", "Ürün kataloğu kurulumu"],
    ),
    (
        "Kurumsal SEO",
        "Arama motoru optimizasyonu — başlık/açıklama/yapı düzeni, yerel SEO ve içerik iyileştirmeleri.",
        [],
        ["Başlık, açıklama, H1 ve yerel anahtar kelime eksikleri Google'daki görünürlüğü düşürür."],
        ["Sayfa içi SEO denetimi ve düzeltmeleri", "Yerel SEO (şehir/ilçe + hizmet) kurgusu", "Yapılandırılmış veri (schema) ekleme"],
    ),
    (
        "Yerel SEO",
        "Şehir/ilçe odaklı arama görünürlüğü: yerel anahtar kelimeler, hizmet-bölge sayfaları, harita paketi ve yerel içerik.",
        [],
        ["'hizmet + şehir/ilçe' aramalarında görünmeyen işletme, yakındaki hazır müşteriyi rakibe kaptırır."],
        ["Şehir/ilçe odaklı hizmet sayfaları", "Yerel anahtar kelime kurgusu", "Yerel schema ve harita entegrasyonu"],
    ),
    (
        "Google İşletme Profili Optimizasyonu",
        "Google İşletme Profilinin eksiksiz doldurulması: kategori, açıklama, hizmetler, fotoğraf, yorum yönetimi.",
        [],
        ["Eksik/zayıf profil, Google Haritalar'da rakiplerin gerisinde kalmaya ve arama başına daha az tıklamaya yol açar."],
        ["Profil düzenleme ve kategori optimizasyonu", "Fotoğraf planı", "Yorum toplama ve yanıtlama süreci"],
    ),
    (
        "Google Ads",
        "Google arama ağı reklam kampanyaları (yerel ve hizmet odaklı).",
        [],
        ["Ticari niyeti yüksek aramalarda reklamla görünmek, organik sıralama yükselene kadar talep sağlar."],
        ["Kampanya kurulumu", "Anahtar kelime araştırması", "Reklam metni ve raporlama"],
    ),
    (
        "Sosyal Medya Yönetimi",
        "Instagram/Facebook içerik planlama, tasarım ve yönetimi.",
        [],
        ["Düzenli ve profesyonel sosyal medya varlığı, işletmeye güveni ve tekrar müşteri oranını artırır."],
        ["Aylık içerik planı", "Görsel/metin üretimi", "Paylaşım ve etkileşim yönetimi"],
    ),
    (
        "Sosyal Medya Reklamları",
        "Instagram/Facebook reklam kampanyaları: hedef kitle kurgusu, görsel/metin üretimi ve optimizasyon.",
        [],
        ["Hesabı olan ama reklam kullanmayan işletme, yerel hedef kitleye ücretli erişim fırsatını kaçırır."],
        ["Kampanya kurulumu", "Reklam görselleri ve metinleri", "Raporlama ve optimizasyon"],
    ),
    (
        "Grafik Tasarım",
        "Logo, kurumsal kimlik, sosyal medya ve baskı görselleri tasarımı.",
        [],
        ["Tutarlı ve profesyonel görsel kimlik, hem dijitalde hem fiziksel mekanda güven verir."],
        ["Logo/kurumsal kimlik", "Sosyal medya görselleri", "Baskı tasarımları"],
    ),
    (
        "Kurumsal Kimlik",
        "Logo, renk/tipografi sistemi, kartvizit, antetli kağıt ve marka kılavuzu.",
        [],
        ["Tutarlı bir marka kimliği hem dijitalde hem fiziksel mekânda güven ve tanınırlık sağlar."],
        ["Logo ve marka kılavuzu", "Kurumsal basılı set", "Dijital kimlik uyarlamaları"],
    ),
    (
        "Fotoğraf ve Video İçerik",
        "Profesyonel işletme/ürün/ekip fotoğrafı ve tanıtım videosu çekimi.",
        [],
        ["Güncel ve kaliteli görsel; Google profilinde, sitede ve sosyal medyada tıklama ve güveni artırır."],
        ["Mekân/ürün/ekip fotoğraf çekimi", "Tanıtım videosu", "Profil ve site için görsel seti"],
    ),
    (
        "Davetiye",
        "Düğün, açılış, etkinlik ve kurumsal organizasyonlar için özel tasarım davetiye ve etkinlik basılı materyalleri.",
        [],
        ["Etkinlik/organizasyon yapan işletmelerde davetiye, etkinliğin ilk izlenimidir."],
        ["Davetiye tasarımı", "Davetiye baskısı ve teslimi"],
    ),
    (
        "Logo Tasarımı",
        "İşletme için yeni veya yenilenmiş logo tasarımı ve kullanım kılavuzu.",
        [],
        ["Güncel ve okunaklı bir logo, her mecrada tutarlı ve profesyonel görünmenin temelidir."],
        ["Logo tasarımı", "Renk ve yazı tipi seti", "Kullanım kılavuzu"],
    ),
    (
        "Sosyal Medya İçerik Üretimi",
        "Ürün, hizmet ve mekân için aylık görsel ve kısa video (reels/story) içerik üretimi.",
        [],
        ["Düzenli ve profesyonel içerik, sosyal medyanın ve Google profilinin canlı görünmesini sağlar."],
        ["Aylık içerik takvimi", "Görsel/video üretimi", "Paylaşım metinleri"],
    ),
    (
        "Kartvizit",
        "Kurumsal kimliğe uygun kartvizit tasarımı ve baskısı.",
        [],
        ["Kartvizit, yüz yüze ve randevulu işlerde işletmenin ilk temsilcisidir."],
        ["Kartvizit tasarımı", "Baskı ve teslimat"],
    ),
    (
        "Broşür",
        "Hizmet ve ürün tanıtım broşürü tasarımı ve baskısı.",
        [],
        ["Anlatılması gereken hizmeti olan işletmelerde broşür karar sürecini destekler."],
        ["Broşür tasarımı", "Baskı ve teslimat"],
    ),
    (
        "Menü Baskı",
        "Restoran/kafe için menü tasarımı ve basılı/QR menü hazırlığı.",
        [],
        ["Yeme-içmede menü satışı doğrudan etkileyen görsel bir araçtır."],
        ["Menü tasarımı", "Baskı ve QR menü"],
    ),
    (
        "Katalog",
        "Ürün/proje kataloğu tasarımı ve baskısı (basılı + PDF).",
        [],
        ["Ürün ve proje odaklı işletmelerde katalog satış görüşmelerini güçlendirir."],
        ["Katalog tasarımı", "Baskı ve PDF"],
    ),
    (
        "Araç Giydirme",
        "Servis/filo araçlarına marka giydirme: tasarım, baskı ve uygulama.",
        [],
        ["Araçlar hareketli reklam alanıdır; markayı bölgede görünür kılabilir."],
        ["Araç giydirme tasarımı", "Baskı ve uygulama"],
    ),
    (
        "Matbaa",
        "Kartvizit, broşür, katalog, menü gibi baskı ürünleri.",
        [],
        ["Fiziksel tanıtım materyaline ihtiyaç duyan işletmeler için."],
        ["Kartvizit", "Broşür/katalog/menü baskısı"],
    ),
    (
        "Branda Baskı",
        "Branda, afiş ve büyük format baskı uygulamaları.",
        [],
        ["Mekanın dışına yönelik görünürlük ve kampanya duyurusu için büyük format baskı."],
        ["Branda/afiş baskı ve montaj"],
    ),
    (
        "Tabela",
        "İşletme tabelası ve dış mekan reklam uygulamaları.",
        [],
        ["Yoldan geçen müşteri işletmeyi tabelasından tanır; okunaklı ve güncel tabela fiziksel görünürlüğün temelidir."],
        ["Tabela tasarımı, üretimi ve montajı"],
    ),
    (
        "Promosyon Ürünleri",
        "Marka logolu promosyon/hediyelik ürün üretimi.",
        [],
        ["Müşteri sadakati ve marka bilinirliği için logolu promosyon ürünleri."],
        ["Promosyon ürün tasarımı ve üretimi"],
    ),
]

INTEGRATIONS = [
    dict(
        name="google_maps_web",
        terms_url="https://cloud.google.com/maps-platform/terms",
        quota_config={
            "note": "Resmi API değildir: herkese açık Google Haritalar sayfası tarayıcıyla okunur. Düşük hacim, kaynak başına minimum bekleme ve 7 günlük önbellek uygulanır; engel (CAPTCHA/consent) görülürse durulur.",
            "min_interval_seconds": 4,
        },
        cache_policy={"default_ttl_days": 7, "note": "Araştırma sonucu 7 gün önbelleklenir; kullanıcı 'Analizi Yenile' derse yeniden sorgulanır."},
        requires_oauth=False,
        attribution_requirements="Google Haritalar verisi gösterilen ekranlarda kaynağı (Google) belirtilir.",
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


def _seed_sectors(db) -> None:
    # 1) Eski (İngilizce/karışık) adlar yerinde yeniden adlandırılır — bağlı işletme kayıtları korunur.
    for old_name, new_name in SECTOR_RENAMES.items():
        if old_name == new_name:
            continue
        old = db.query(Sector).filter_by(name=old_name).one_or_none()
        if old is None:
            continue
        if db.query(Sector).filter_by(name=new_name).one_or_none() is None:
            old.name = new_name
            db.flush()
        else:
            # Yeni ad zaten var: eskiyi pasife al (kullanımdaysa silinmez).
            old.is_active = False

    # 2) Güncel liste: yoksa ekle, varsa etiket/anahtar kelime/grup bilgisini yenile.
    for name, group, search_terms in SECTORS:
        sector = db.query(Sector).filter_by(name=name).one_or_none()
        if sector is None:
            db.add(Sector(name=name, group_name=group, google_place_types=[], keyword_variants=search_terms, is_active=True))
        else:
            sector.group_name = group
            sector.google_place_types = []  # eski (OpenStreetMap etiketi) alan artık kullanılmıyor
            sector.keyword_variants = search_terms
            sector.is_active = True
    db.flush()

    # 3) Artık listede olmayan eski kayıtlar: kullanılmıyorsa sil, kullanılıyorsa pasife al.
    for obsolete_name in OBSOLETE_SECTOR_NAMES:
        sector = db.query(Sector).filter_by(name=obsolete_name).one_or_none()
        if sector is None:
            continue
        if db.query(Business).filter_by(sector_id=sector.id).first() is not None:
            sector.is_active = False
        else:
            db.delete(sector)


def _seed_services(db) -> None:
    for old_name, new_name in SERVICE_RENAMES.items():
        old = db.query(ServiceCatalog).filter_by(service_name=old_name).one_or_none()
        if old is not None and db.query(ServiceCatalog).filter_by(service_name=new_name).one_or_none() is None:
            old.service_name = new_name
    db.flush()

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
        else:
            service.description = description
            service.sales_arguments = sales_arguments
            service.deliverables = deliverables
    db.flush()


def run():
    db = SessionLocal()
    try:
        _seed_regions(db)

        _seed_sectors(db)

        _seed_services(db)

        for integration in INTEGRATIONS:
            stmt = pg_insert(IntegrationRegistry).values(**integration)
            stmt = stmt.on_conflict_do_update(index_elements=["name"], set_=integration)
            db.execute(stmt)

        db.commit()
        region_count = db.query(Region).count()
        print(
            f"Seed OK: {region_count} bölge (81 il + ilçeler), {len(SECTORS)} sektör, "
            f"{len(SERVICES)} hizmet, {len(INTEGRATIONS)} entegrasyon kaydı."
        )
    except IntegrityError:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
