"""Sprint 0 seed data: regions, starter sectors, integrations_registry.

Run with: python -m packages.db.seed
Idempotent: safe to re-run (upserts by natural key).
"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.db.base import SessionLocal
from packages.db.models import Region, Sector, IntegrationRegistry, ServiceCatalog

REGIONS = [
    # name, level, parent_name, center_lat, center_lng, search_radius_m
    ("Sakarya", "il", None, 40.7569, 30.3781, 25000),
    ("Adapazarı", "ilce", "Sakarya", 40.7833, 30.4000, 8000),
    ("Serdivan", "ilce", "Sakarya", 40.7550, 30.3400, 6000),
    ("Erenler", "ilce", "Sakarya", 40.7500, 30.4300, 6000),
    ("Kocaeli", "il", None, 40.8533, 29.8815, 25000),
]

SECTORS = [
    # name, google_place_types, keyword_variants
    ("Restoran", ["restaurant"], ["restoran", "lokanta", "kebapçı", "cafe", "kafe"]),
    ("Web Tasarım İhtiyacı Olabilecek Tüm İşletmeler", [], []),
    ("Kuaför / Güzellik Salonu", ["hair_care", "beauty_salon"], ["kuaför", "güzellik salonu", "berber"]),
    ("Emlak", ["real_estate_agency"], ["emlak", "emlakçı"]),
    ("Otomotiv Servisi", ["car_repair"], ["oto servis", "oto tamir", "lastikçi"]),
    ("Mobilya", ["furniture_store"], ["mobilya", "mobilyacı"]),
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
                region = Region(
                    name=name,
                    level=level,
                    center_lat=lat,
                    center_lng=lng,
                    search_radius_m=radius,
                )
                db.add(region)
                db.flush()
            region_ids_by_name[name] = region.id

        for name, level, parent_name, *_ in REGIONS:
            if parent_name:
                region = db.query(Region).filter_by(name=name).one()
                region.parent_region_id = region_ids_by_name[parent_name]

        for name, place_types, keywords in SECTORS:
            sector = db.query(Sector).filter_by(name=name).one_or_none()
            if sector is None:
                db.add(Sector(name=name, google_place_types=place_types, keyword_variants=keywords))

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
    finally:
        db.close()


if __name__ == "__main__":
    run()
