from packages.config import settings
from services.integrations.website_crawler.base import WebsiteAnalyzer


def get_website_analyzer(*, business_is_demo: bool) -> WebsiteAnalyzer:
    """DEMO işletmeler (discovery_source == mock_demo) her zaman mock analizör kullanır —
    gerçek olmayan bir URL'e HTTP isteği atmanın hiçbir anlamı yok. Gerçek keşifle
    bulunan işletmeler DISCOVERY_PROVIDER ayarına göre gerçek crawler'ı kullanır.
    """
    if business_is_demo or settings.discovery_provider == "mock":
        from services.integrations.website_crawler.mock_analyzer import MockWebsiteAnalyzer

        return MockWebsiteAnalyzer()

    from services.integrations.website_crawler.real_crawler import RealWebsiteCrawler

    return RealWebsiteCrawler()
