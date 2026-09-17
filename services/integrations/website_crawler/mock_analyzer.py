"""DEMO web sitesi analizörü — gerçek bir HTTP isteği ATMAZ.

Mock Discovery ile bulunan işletmelerin website alanı zaten gerçekte var
olmayan (`*.invalid`) adreslerdir; bunlara gerçek bir crawler ile bağlanmaya
çalışmak sadece deterministik bir bağlantı hatası üretir. Bunun yerine, aynı
Finding/Rule Engine/Scoring mimarisini uçtan uca DEMO modunda da anlamlı
şekilde test edebilmek için deterministik-ama-açıkça-kurgusal sinyaller üretir.

Business.discovery_source == "mock_demo" olan işletmeler için kullanılır;
UI'da "DEMO DATA" etiketiyle birlikte gösterilir, gerçek veri gibi sunulmaz.
"""

import hashlib

from services.integrations.website_crawler.base import WebsiteAnalyzer, WebsiteSignals


def _deterministic_bit(url: str, salt: str, modulo: int = 2) -> int:
    digest = hashlib.sha1(f"{url}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


class MockWebsiteAnalyzer(WebsiteAnalyzer):
    def analyze(self, url: str) -> WebsiteSignals:
        return WebsiteSignals(
            success=True,
            https_enabled=_deterministic_bit(url, "https") == 0,
            title_present=_deterministic_bit(url, "title", 5) != 0,
            meta_description_present=_deterministic_bit(url, "meta_desc", 2) == 0,
            h1_present=_deterministic_bit(url, "h1", 3) != 0,
            schema_markup_present=_deterministic_bit(url, "schema", 4) == 0,
            whatsapp_link_present=_deterministic_bit(url, "whatsapp", 2) == 0,
            phone_link_present=_deterministic_bit(url, "phone_link", 2) == 0,
            reservation_link_present=_deterministic_bit(url, "reservation", 4) == 0,
            instagram_link_present=_deterministic_bit(url, "instagram", 2) == 0,
            facebook_link_present=_deterministic_bit(url, "facebook", 3) == 0,
            page_load_ms=float(300 + _deterministic_bit(url, "load_ms", 2000)),
        )
