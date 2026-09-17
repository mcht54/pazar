"""Gerçek web sitesi crawler'ı — sadece robots.txt'in izin verdiği public sayfaları çeker.

Kullanım şartı notu: Bu, arama motorlarının yaptığına benzer, kamuya açık bir
homepage taraması yapar (resmi bir API'si olmayan tek entegrasyon budur —
bkz. design doc madde 12). Login/özel alan taramaz, sadece homepage.
"""

import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from services.integrations.website_crawler.base import WebsiteAnalyzer, WebsiteSignals

REQUEST_TIMEOUT_SECONDS = 6.0
MAX_RETRIES = 2
RETRY_BACKOFF_BASE_SECONDS = 1.0
USER_AGENT = "MchttasarimMarketingOS/0.1 (+https://mchttasarim.com; discovery-bot)"


def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except Exception:
        # robots.txt okunamıyorsa (site yok/erişilemiyor) tarama zaten başarısız olacak; izin var varsayılır.
        return True
    return parser.can_fetch(USER_AGENT, url)


class RealWebsiteCrawler(WebsiteAnalyzer):
    def analyze(self, url: str) -> WebsiteSignals:
        if not _robots_allows(url):
            return WebsiteSignals(success=False, error_reason="robots.txt taramaya izin vermiyor")

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                start = time.monotonic()
                with httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                    response = client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                elapsed_ms = (time.monotonic() - start) * 1000
                response.raise_for_status()
                return self._parse(response, elapsed_ms)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError, httpx.RequestError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_BASE_SECONDS * attempt)

        return WebsiteSignals(success=False, error_reason=f"İstek başarısız: {last_exc}")

    def _parse(self, response: httpx.Response, elapsed_ms: float) -> WebsiteSignals:
        soup = BeautifulSoup(response.text, "html.parser")

        meta_description = soup.find("meta", attrs={"name": "description"})
        h1 = soup.find("h1")
        schema_script = soup.find("script", attrs={"type": "application/ld+json"})

        links = [a.get("href", "") for a in soup.find_all("a")]
        has_whatsapp = any("wa.me" in href or "whatsapp.com" in href for href in links)
        has_tel = any(href.startswith("tel:") for href in links)
        has_reservation = any(
            keyword in href.lower() for href in links for keyword in ("rezervasyon", "reservation", "randevu")
        )
        has_instagram = any("instagram.com" in href for href in links)
        has_facebook = any("facebook.com" in href for href in links)

        return WebsiteSignals(
            success=True,
            https_enabled=str(response.url).startswith("https://"),
            title_present=bool(soup.title and soup.title.string and soup.title.string.strip()),
            meta_description_present=bool(meta_description and meta_description.get("content", "").strip()),
            h1_present=bool(h1 and h1.get_text(strip=True)),
            schema_markup_present=bool(schema_script),
            whatsapp_link_present=has_whatsapp,
            phone_link_present=has_tel,
            reservation_link_present=has_reservation,
            instagram_link_present=has_instagram,
            facebook_link_present=has_facebook,
            page_load_ms=round(elapsed_ms, 1),
        )
