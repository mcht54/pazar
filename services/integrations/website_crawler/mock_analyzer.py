"""DEMO web sitesi analizörü — gerçek bir HTTP isteği ATMAZ.

Mock Discovery ile bulunan işletmelerin website alanı zaten gerçekte var
olmayan (`*.invalid`) adreslerdir; bunlara gerçek bir crawler ile bağlanmaya
çalışmak sadece deterministik bir bağlantı hatası üretir. Bunun yerine, aynı
bulgu/kural/satış mimarisini uçtan uca DEMO modunda da test edebilmek için
deterministik-ama-açıkça-kurgusal sinyaller üretir.

Business.discovery_source == "mock_demo" olan işletmeler için kullanılır;
arayüzde "DEMO VERİ" etiketiyle birlikte gösterilir, gerçek veri gibi sunulmaz.
"""

import hashlib

from services.integrations.website_crawler.base import WebsiteAnalyzer, WebsiteSignals


def _bit(url: str, salt: str, modulo: int = 2) -> int:
    digest = hashlib.sha1(f"{url}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


class MockWebsiteAnalyzer(WebsiteAnalyzer):
    def analyze(self, url: str, *, light: bool = False) -> WebsiteSignals:
        return WebsiteSignals(
            success=True,
            outcome="ok",
            requested_url=url,
            final_url=url,
            http_status=200,
            https_enabled=_bit(url, "https") == 0,
            response_ms=float(300 + _bit(url, "load_ms", 2000)),
            html_bytes=50_000,
            title="Demo Sayfa" if _bit(url, "title", 5) != 0 else None,
            meta_description="Demo açıklama" if _bit(url, "meta_desc") == 0 else None,
            h1_texts=["Demo Başlık"] if _bit(url, "h1", 3) != 0 else [],
            h2_count=2,
            h3_count=1,
            viewport_ok=_bit(url, "viewport") == 0,
            word_count=250,
            text_excerpt="demo içerik",
            images_total=10,
            images_missing_alt=_bit(url, "alt", 10),
            schema_types=["LocalBusiness"] if _bit(url, "schema", 4) == 0 else [],
            tel_link_present=_bit(url, "phone_link") == 0,
            whatsapp_link_present=_bit(url, "whatsapp") == 0,
            maps_link_present=_bit(url, "maps") == 0,
            form_present=_bit(url, "form") == 0,
            social_links={"instagram": "https://instagram.com/demo"} if _bit(url, "instagram") == 0 else {},
            has_services_page=_bit(url, "services") == 0,
            has_about_page=True,
            has_references_page=False,
            has_blog=False,
            has_contact_page=True,
            has_appointment_link=_bit(url, "reservation", 4) == 0,
            has_shop_signals=False,
            sitemap_present=_bit(url, "sitemap") == 0,
            links_checked=0,
        )
