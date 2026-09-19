"""Gerçek web sitesi analizörü — ana sayfayı gerçekten açar ve ölçer.

Kurallar (dürüstlük + nezaket + güvenlik):
- robots.txt taramaya izin vermiyorsa sayfa AÇILMAZ; sonuç "analiz edilemedi" olur (engel aşılmaz).
- Bot koruması (Cloudflare, 403/429...) site hatası gibi raporlanmaz: "erişim engellendi, analiz edilemedi".
- Sadece ana sayfa + sitemap.xml + aynı siteden en fazla birkaç iç bağlantı (kırık bağlantı kontrolü)
  istenir. Giriş gerektiren/özel alan taranmaz.
- Adresler OSM/Google gibi güvenilmeyen kaynaktan geldiği için özel ağ adreslerine (localhost,
  192.168.x.x ...) istek atılmaz (SSRF koruması); yönlendirmeler her adımda yeniden denetlenir.
- Ölçülemeyen değer None kalır; tahmin edilmez.
"""

import ipaddress
import json
import re
import socket
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from packages.config import settings
from packages.localization import fold
from services.research.normalize import extract_phones, normalize_phone
from services.integrations.website_crawler.base import WebsiteAnalyzer, WebsiteSignals

REQUEST_TIMEOUT_SECONDS = 10.0
ROBOTS_TIMEOUT_SECONDS = 5.0
LINK_CHECK_TIMEOUT_SECONDS = 5.0
PAGESPEED_TIMEOUT_SECONDS = 60.0
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 1.0
MAX_HTML_BYTES = 3_000_000
MAX_LINKS_TO_CHECK = 10
TEXT_EXCERPT_CHARS = 6000
USER_AGENT = "MchttasarimMarketingOS/0.1 (+https://mchttasarim.com; web-analiz-botu)"

# "Web sitesi" alanına yazılmış ama gerçekte web sitesi olmayan adres türleri.
SOCIAL_HOSTS = (
    "instagram.com", "facebook.com", "fb.com", "fb.me", "twitter.com", "x.com", "linkedin.com",
    "tiktok.com", "youtube.com", "youtu.be", "wa.me", "whatsapp.com", "linktr.ee", "linkin.bio",
    "t.me", "pinterest.com",
)
LISTING_HOSTS = (
    "sahibinden.com", "trendyol.com", "hepsiburada.com", "yemeksepeti.com", "getir.com",
    "booking.com", "tripadvisor.com", "tripadvisor.com.tr", "g.page", "business.site",
    "maps.app.goo.gl", "goo.gl",
)
SKIPPED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip", ".rar", ".doc", ".docx",
    ".xls", ".xlsx", ".mp4", ".mp3", ".css", ".js", ".xml",
)

_BOT_BLOCK_MARKERS = ("just a moment", "cf-browser-verification", "cf-chl", "attention required", "captcha", "access denied")
_ECOMMERCE_MARKERS = (
    "woocommerce", "shopify", "ticimax", "ikas", "ideasoft", "tsoft", "sepete ekle", "add to cart",
    "add-to-cart", "sepetim", "/sepet", "/cart", "/checkout", "odeme",
)
_ANALYTICS_MARKERS = {
    # Yalnızca gerçek izleme kodu işaretleri (sınıf adı/metin içinde rastlanabilecek "ua-", "gtm-" gibi kısa parçalar tırnakla sınırlandırılır)
    "ga4": ("gtag/js?id=g-", "'g-", '"g-'),
    "universal_analytics": ("google-analytics.com/analytics.js", "'ua-", '"ua-', "ga('create'"),
    "gtm": ("googletagmanager.com/gtm.js", "'gtm-", '"gtm-'),
    "google_ads": ("googleadservices.com", "'aw-", '"aw-', "google_conversion", "conversion_async"),
    "meta_pixel": ("connect.facebook.net/", "fbq("),
    "hotjar": ("static.hotjar.com",),
    "clarity": ("clarity.ms",),
    "yandex_metrica": ("mc.yandex.ru",),
}
_CTA_WORDS = ("hemen ara", "simdi ara", "randevu al", "teklif al", "fiyat al", "ucretsiz", "iletisime gec", "bize ulasin", "siparis ver", "rezervasyon yap", "hemen basvur", "kayit ol", "whatsapp ile")
_NAV_KEYWORDS = {
    "has_services_page": ("hizmet", "service", "urun", "urunler", "menu", "tedavi", "cihaz", "kategori", "cozum"),
    "has_about_page": ("hakkimizda", "about", "kurumsal", "biz kimiz", "hakkinda"),
    "has_references_page": ("referans", "reference", "proje", "portfolio", "galeri", "gallery", "calismalarimiz"),
    "has_blog": ("blog", "haber", "makale", "yazilar", "duyuru"),
    "has_contact_page": ("iletisim", "contact", "bize ulasin", "ulasim"),
    "has_appointment_link": ("randevu", "rezervasyon", "reservation", "booking", "appointment"),
    "has_catalog_page": ("katalog", "catalog", "menu", "urunler", "fiyat listesi", "fiyatlar"),
}
SPAM_TERMS = ("bokep", "porno", "porn", "xxx", "sex", "casino", "bahis", "slot gacor", "judi", "viagra", "escort", "kumar", "bet365", "canli bahis")
# Sayfa altı "web tasarım / yazılım: X", "Designed by X" kredisi — mevcut web/dijital sağlayıcı kanıtı. Yalnızca dış bağlantı ya da açık "cue: Ad" metni kabul edilir.
_AGENCY_CUE_RE = re.compile(
    r"(web\s*tasar[ıi]m|site\s*tasar[ıi]m|web\s*yaz[ıi]l[ıi]m|yaz[ıi]l[ıi]m|tasar[ıi]m|web\s*ajans[ıi]?|web\s*geli[şs]tirme|"
    r"designed\s+(?:and\s+developed\s+)?by|design\s+by|developed\s+by|development\s+by|created\s+by|made\s+by|crafted\s+by|powered\s+by|built\s+by)",
    re.IGNORECASE,
)
_AGENCY_TEXT_RE = re.compile(  # bağlantısız kredi: İngilizce "… by Ad" ya da Türkçe "Web Tasarım: Ad" (ayraçlı)
    r"(?:(?:designed\s+(?:and\s+developed\s+)?by|design\s+by|developed\s+by|development\s+by|created\s+by|made\s+by|crafted\s+by|built\s+by)\s*[:\-–|]?\s*"
    r"|(?:web\s*tasar[ıi]m|site\s*tasar[ıi]m|web\s*yaz[ıi]l[ıi]m|yaz[ıi]l[ıi]m|tasar[ıi]m|web\s*ajans[ıi]?)\s*[:\-–|]\s*)"
    r"(?P<name>[A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü .&'-]{2,40})", re.IGNORECASE)
_PLATFORM_HOSTS = ("wix.com", "wordpress.org", "wordpress.com", "shopify.com", "squarespace.com", "webflow.com", "godaddy.com", "weebly.com", "jimdo.com", "ticimax.com", "ideasoft.com.tr", "tsoft.com.tr", "ikas.com", "elementor.com")
_NOT_AGENCY_HOSTS = ("instagram.com", "facebook.com", "youtube.com", "twitter.com", "x.com", "linkedin.com", "tiktok.com", "google.com", "goo.gl", "wa.me", "whatsapp.com", "maps.app.goo.gl")


def _host(url: str) -> str:
    return urlparse(url if "//" in url else f"//{url}").netloc.lower().removeprefix("www.")


def find_agency_credit(soup: BeautifulSoup, site_host: str) -> dict | None:
    """Alt bilgi (footer) alanında geliştirici/ajans kredisi arar. Bulunamazsa None — bu, ajans OLMADIĞI anlamına gelmez."""
    footer = soup.find("footer") or soup.find(id=re.compile("footer", re.I)) or soup.find(class_=re.compile("footer", re.I))
    if footer is None:
        return None
    for node in footer.find_all(string=_AGENCY_CUE_RE):
        container = node.parent
        for _ in range(3):  # metnin bulunduğu öğe ve en fazla 2 üst öğe içinde dış bağlantı ara
            if container is None:
                break
            for a in container.find_all("a", href=True):
                href = a["href"].strip()
                host = _host(href)
                if href.startswith(("http", "//")) and host and host != site_host and not any(host.endswith(h) for h in _NOT_AGENCY_HOSTS):
                    text = re.sub(r"\s+", " ", container.get_text(" ", strip=True))[:140]
                    name = a.get_text(" ", strip=True) or host
                    kind = "platform" if any(host.endswith(h) for h in _PLATFORM_HOSTS) else "agency"
                    return {"name": name[:80], "url": href[:300], "text": text, "kind": kind}
            container = container.parent
            if container is footer.parent:
                break
        text = re.sub(r"\s+", " ", (node.parent.get_text(" ", strip=True) if node.parent else str(node)))
        match = _AGENCY_TEXT_RE.search(text)
        if match:
            name = re.split(r"\s*[|•·©]|\s{2,}", match.group("name"))[0].strip(" -–:.")
            if len(name) >= 3:
                return {"name": name[:80], "url": None, "text": text[:140], "kind": "agency"}
    return None


_PHONE_RE = re.compile(r"(?:\+?90[\s.-]?|0)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ADDRESS_RE = re.compile(r"\b(mah\.?|mahallesi|cad\.?|caddesi|sok\.?|sokak|bulvar[ıi]?|no\s*:)", re.IGNORECASE)
_COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright|\(c\))\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.IGNORECASE)


def soup_has_meta_verification(raw_html: str) -> bool:
    return 'name="google-site-verification"' in raw_html or "name='google-site-verification'" in raw_html


class _Unreachable(Exception):
    def __init__(self, reason: str, *, kind: str = "connect", ssl_error: bool = False, timeout: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.kind = kind
        self.ssl_error = ssl_error
        self.timeout = timeout


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in domains)


def _classify_listing(url: str) -> str | None:
    """Sosyal medya / harita / pazaryeri adresi ise kısa açıklaması, gerçek site ise None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _host_matches(host, SOCIAL_HOSTS):
        return f"sosyal medya/mesajlaşma adresi ({host.removeprefix('www.')})"
    if _host_matches(host, LISTING_HOSTS):
        return f"harita/pazaryeri/rezervasyon sayfası ({host.removeprefix('www.')})"
    if _host_matches(host, ("google.com",)) and host != "sites.google.com":
        return f"Google sayfası ({host.removeprefix('www.')})"
    return None


def _normalize_url(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    value = re.split(r"[;\s,]", value)[0]  # OSM'de bazen "a.com;b.com" yazılır — ilkini al
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
        return None
    return value


def _ensure_public(url: str) -> None:
    host = urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise _Unreachable("Alan adı çözümlenemedi (site kapalı ya da alan adı süresi dolmuş olabilir)", kind="dns") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise _Unreachable("Adres özel bir ağa işaret ediyor — güvenlik nedeniyle taranmadı", kind="private")


def _open(client: httpx.Client, method: str, url: str, *, timeout: float, read_body: bool):
    """Yönlendirmeleri elle izleyerek (her adımda genel-adres denetimiyle) isteği yapar.

    Döndürür: (status, final_url, headers, body_bytes)
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _ensure_public(current)
        try:
            with client.stream(method, current, timeout=timeout) as response:
                location = response.headers.get("location")
                if response.status_code in (301, 302, 303, 307, 308) and location:
                    current = urljoin(current, location)
                    continue
                body = bytearray()
                if read_body:
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > MAX_HTML_BYTES:
                            break
                return response.status_code, current, response.headers, bytes(body)
        except httpx.TimeoutException as exc:
            raise _Unreachable("Site yanıt vermedi (zaman aşımı)", kind="timeout", timeout=True) from exc
        except httpx.ConnectError as exc:
            message = str(exc).lower()
            if "certificate" in message or "ssl" in message:
                raise _Unreachable("SSL sertifikası geçersiz veya süresi dolmuş", kind="ssl", ssl_error=True) from exc
            if any(t in message for t in ("name or service not known", "nodename", "getaddrinfo", "name resolution")):
                raise _Unreachable("Alan adı çözümlenemedi (site kapalı ya da alan adı süresi dolmuş olabilir)", kind="dns") from exc
            raise _Unreachable("Sunucuya bağlanılamadı", kind="connect") from exc
        except httpx.RequestError as exc:
            raise _Unreachable(f"Bağlantı hatası ({type(exc).__name__})") from exc
    raise _Unreachable("Çok fazla yönlendirme (yönlendirme döngüsü olabilir)", kind="redirect")


def _looks_bot_blocked(status: int, headers, body: bytes) -> bool:
    if status in (401, 403, 429):
        return True
    server = (headers.get("server") or "").lower()
    head = body[:20000].decode("utf-8", errors="ignore").lower()
    if status in (503, 202) and ("cloudflare" in server or any(m in head for m in _BOT_BLOCK_MARKERS)):
        return True
    if status == 200 and len(body) < 30000 and any(m in head for m in _BOT_BLOCK_MARKERS[:3]):
        return True
    return False


def _schema_types(soup: BeautifulSoup) -> list[str]:
    types: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            node_type = node.get("@type")
            if isinstance(node_type, str):
                types.append(node_type)
            elif isinstance(node_type, list):
                types.extend(t for t in node_type if isinstance(t, str))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            walk(json.loads(script.string or script.get_text() or ""))
        except (ValueError, TypeError):
            types.append("(okunamayan JSON-LD)")
    return sorted(set(types))


class RealWebsiteCrawler(WebsiteAnalyzer):
    def analyze(self, url: str, *, light: bool = False) -> WebsiteSignals:
        normalized = _normalize_url(url)
        if normalized is None:
            return WebsiteSignals(
                success=False, outcome="invalid_url", requested_url=url,
                error_reason="Web sitesi adresi geçerli bir biçimde değil",
            )

        listing = _classify_listing(normalized)
        if listing:
            return WebsiteSignals(
                success=False, outcome="not_a_website", requested_url=normalized, final_url=normalized,
                error_reason=f"Web sitesi alanında gerçek bir site yerine {listing} girilmiş",
            )

        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "tr,en;q=0.8"}) as client:
            return self._analyze_with_client(client, normalized, light=light)

    # ------------------------------------------------------------------ ana akış
    def _analyze_with_client(self, client: httpx.Client, url: str, *, light: bool = False) -> WebsiteSignals:
        signals = WebsiteSignals(success=False, requested_url=url)

        # robots.txt: izin yoksa sayfa hiç açılmaz.
        try:
            allowed, sitemaps = self._robots(client, url)
        except _Unreachable as exc:
            signals.outcome, signals.error_reason, signals.failure_kind = "unreachable", exc.reason, exc.kind
            return signals
        if not allowed:
            signals.outcome = "robots_disallowed"
            signals.error_reason = "robots.txt taramaya izin vermediği için site analiz edilemedi"
            return signals

        fetched = self._fetch_home(client, url, signals)
        if fetched is None:
            return signals
        status, final_url, headers, body, elapsed_ms = fetched

        signals.http_status = status
        signals.final_url = final_url
        signals.response_ms = round(elapsed_ms, 1)
        signals.html_bytes = len(body)
        signals.https_enabled = final_url.startswith("https://") and not signals.ssl_error

        redirected_listing = _classify_listing(final_url)
        if redirected_listing:
            signals.outcome = "not_a_website"
            signals.error_reason = f"Web sitesi alanındaki adres gerçek bir siteye değil, {redirected_listing} yönleniyor"
            return signals

        if _looks_bot_blocked(status, headers, body):
            signals.outcome = "blocked"
            signals.error_reason = "Site bot korumasıyla erişimi engelledi (site bozuk olmayabilir) — analiz edilemedi"
            return signals
        if status in (404, 410):
            signals.outcome, signals.error_reason, signals.failure_kind = "unreachable", f"Sayfa bulunamadı (HTTP {status})", "http_404"
            return signals
        if status >= 400:
            signals.outcome, signals.error_reason, signals.failure_kind = "unreachable", f"Site hata döndürdü (HTTP {status})", "http_error"
            return signals
        content_type = (headers.get("content-type") or "").lower()
        if content_type and "html" not in content_type:
            signals.outcome, signals.error_reason = "unreachable", f"Adres bir web sayfası döndürmüyor ({content_type.split(';')[0]})"
            return signals

        signals.success = True
        signals.outcome = "ok"
        self._parse(BeautifulSoup(body, "html.parser"), final_url, signals)
        self._contact_page(client, final_url, signals)
        if not light:
            self._technical_checks(client, final_url, sitemaps, signals, BeautifulSoup(body, "html.parser"))
            signals.pagespeed, signals.pagespeed_error = self._pagespeed(final_url)
        return signals

    def _fetch_home(self, client: httpx.Client, url: str, signals: WebsiteSignals):
        """Ana sayfayı çeker; başarısızlıkta signals'ı doldurup None döndürür."""
        candidates = [url]
        if url.startswith("https://"):
            candidates.append("http://" + url[len("https://"):])  # https hiç çalışmıyorsa http'yi de dene

        last_error: _Unreachable | None = None
        for candidate in candidates:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                start = time.monotonic()
                try:
                    status, final_url, headers, body = _open(client, "GET", candidate, timeout=REQUEST_TIMEOUT_SECONDS, read_body=True)
                    return status, final_url, headers, body, (time.monotonic() - start) * 1000
                except _Unreachable as exc:
                    last_error = exc
                    if exc.ssl_error:
                        # Sertifika geçersiz: gerçek bir bulgu — yine de içeriği analiz edebilmek için doğrulamasız dene.
                        try:
                            with httpx.Client(headers=dict(client.headers), verify=False) as insecure:
                                status, final_url, headers, body = _open(insecure, "GET", candidate, timeout=REQUEST_TIMEOUT_SECONDS, read_body=True)
                            signals.ssl_error = True
                            return status, final_url, headers, body, (time.monotonic() - start) * 1000
                        except _Unreachable as inner:
                            last_error = inner
                        break
                    if not (exc.timeout) or attempt == MAX_ATTEMPTS:
                        break
                    time.sleep(RETRY_BACKOFF_SECONDS)

        signals.outcome = "unreachable"
        signals.error_reason = last_error.reason if last_error else "Siteye erişilemedi"
        signals.failure_kind = last_error.kind if last_error else "connect"
        signals.ssl_error = bool(last_error and last_error.ssl_error) or None
        return None

    # ------------------------------------------------------------------ robots / sitemap
    def _robots(self, client: httpx.Client, url: str) -> tuple[bool, list[str]]:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        _ensure_public(url)
        try:
            status, _final, _headers, body = _open(client, "GET", robots_url, timeout=ROBOTS_TIMEOUT_SECONDS, read_body=True)
        except _Unreachable:
            return True, []  # robots.txt okunamıyorsa ana sayfa denemesi zaten asıl hatayı üretir
        if status != 200:
            return True, []
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.decode("utf-8", errors="ignore").splitlines())
        return parser.can_fetch(USER_AGENT, url), list(parser.site_maps() or [])

    def _technical_checks(
        self, client: httpx.Client, final_url: str, robots_sitemaps: list[str], signals: WebsiteSignals, soup: BeautifulSoup
    ) -> None:
        parsed = urlparse(final_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # sitemap.xml
        sitemap_url = robots_sitemaps[0] if robots_sitemaps else f"{origin}/sitemap.xml"
        try:
            status, *_ = _open(client, "HEAD", sitemap_url, timeout=ROBOTS_TIMEOUT_SECONDS, read_body=False)
            if status in (405, 501):
                status, *_ = _open(client, "GET", sitemap_url, timeout=ROBOTS_TIMEOUT_SECONDS, read_body=False)
            signals.sitemap_present = status == 200
        except _Unreachable:
            signals.sitemap_present = None  # ölçülemedi

        # kırık bağlantılar (aynı siteden en fazla MAX_LINKS_TO_CHECK sayfa)
        links = self._internal_links(soup, final_url)[:MAX_LINKS_TO_CHECK]
        signals.links_checked = len(links)
        if not links:
            return

        def check(link: str) -> tuple[str, int | None]:
            try:
                status, *_ = _open(client, "HEAD", link, timeout=LINK_CHECK_TIMEOUT_SECONDS, read_body=False)
                if status in (403, 405, 501):
                    status, *_ = _open(client, "GET", link, timeout=LINK_CHECK_TIMEOUT_SECONDS, read_body=False)
                return link, status
            except _Unreachable:
                return link, None  # zaman aşımı/bağlantı sorunu "kırık" sayılmaz (ölçülemedi)

        with ThreadPoolExecutor(max_workers=5) as pool:
            for link, status in pool.map(check, links):
                if status in (404, 410) or (status is not None and status >= 500 and status != 503):
                    signals.broken_links.append({"url": link, "status": status})

    @staticmethod
    def _internal_links(soup: BeautifulSoup, base_url: str) -> list[str]:
        base_host = (urlparse(base_url).hostname or "").removeprefix("www.")
        seen: set[str] = set()
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "sms:")):
                continue
            absolute = urljoin(base_url, href).split("#")[0]
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if (parsed.hostname or "").removeprefix("www.") != base_host:
                continue
            if parsed.path.lower().endswith(SKIPPED_EXTENSIONS):
                continue
            if "/cdn-cgi/" in parsed.path:
                continue  # Cloudflare'ın iç adresleri (e-posta koruma vb.) botlara 404 döner; kırık bağlantı değildir
            if absolute.rstrip("/") == base_url.rstrip("/") or absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return links

    # ------------------------------------------------------------------ Google PageSpeed (opsiyonel)
    def _pagespeed(self, url: str) -> tuple[dict | None, str | None]:
        key = settings.google_pagespeed_api_key
        if not key:
            return None, "Google PageSpeed API anahtarı tanımlı değil"
        try:
            response = httpx.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params={"url": url, "strategy": "mobile", "category": "performance", "locale": "tr", "key": key},
                timeout=PAGESPEED_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                return None, f"Google PageSpeed yanıt vermedi (HTTP {response.status_code})"
            lighthouse = response.json()["lighthouseResult"]
            audits = lighthouse["audits"]
            score = lighthouse["categories"]["performance"]["score"]
            return {
                "performance_score": round(score * 100) if score is not None else None,
                "lcp_ms": audits.get("largest-contentful-paint", {}).get("numericValue"),
                "cls": audits.get("cumulative-layout-shift", {}).get("numericValue"),
                "tbt_ms": audits.get("total-blocking-time", {}).get("numericValue"),
            }, None
        except (httpx.RequestError, KeyError, ValueError) as exc:
            return None, f"Google PageSpeed sonucu alınamadı ({type(exc).__name__})"

    # ------------------------------------------------------------------ iletişim bilgileri
    @staticmethod
    def _extract_contact_info(anchors, text: str, signals: WebsiteSignals, business: dict | None) -> None:
        """Telefon/e-posta/adres/schema bilgisini sayfadan okur ve signals'a EKLER (var olanlarla birleştirir)."""
        phones = list(signals.phones_found)
        for href in (a["href"] for a in anchors if a["href"].lower().startswith("tel:")):
            number = normalize_phone(href[4:])
            if number and number not in phones:
                phones.append(number)
        for number in extract_phones(text):
            if number not in phones:
                phones.append(number)

        emails = list(signals.emails_found)
        candidates = [a["href"][7:].split("?")[0] for a in anchors if a["href"].lower().startswith("mailto:")] + _EMAIL_RE.findall(text)
        for email in candidates:
            email = email.strip().lower().strip(".,;:()<>")
            if (
                email not in emails
                and re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", email)
                and not email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))
                and "sentry" not in email and "example" not in email and "wixpress" not in email
            ):
                emails.append(email)

        if business:
            signals.schema_business = signals.schema_business or business
            number = normalize_phone(business.get("telephone"))
            if number and number not in phones:
                phones.append(number)
            if business.get("email") and business["email"].lower() not in emails:
                emails.append(business["email"].lower())
            for url in business.get("same_as") or []:
                for network, domain in (("instagram", "instagram.com"), ("facebook", "facebook.com"), ("linkedin", "linkedin.com"), ("youtube", "youtube.com")):
                    if domain in url.lower():
                        signals.social_links.setdefault(network, url)

        signals.phones_found, signals.emails_found = phones[:8], emails[:5]
        if not signals.address_text:
            match = _ADDRESS_RE.search(text)
            if match:
                start = max(0, match.start() - 60)
                signals.address_text = re.sub(r"\s+", " ", text[start : match.end() + 90]).strip()

    @staticmethod
    def _schema_business(soup: BeautifulSoup) -> dict | None:
        """İlk LocalBusiness/Organization benzeri JSON-LD düğümünden ad, telefon, e-posta, adres ve sameAs bağlantıları."""
        found: dict | None = None

        def visit(node):
            nonlocal found
            if found is not None:
                return
            if isinstance(node, dict):
                node_type = node.get("@type")
                types = [node_type] if isinstance(node_type, str) else (node_type if isinstance(node_type, list) else [])
                if any(t in ("LocalBusiness", "Organization", "Store", "MedicalBusiness", "HealthAndBeautyBusiness", "Dentist", "Physician", "Restaurant", "Hotel", "AutoRepair", "ProfessionalService")
                       or str(t).endswith("Business") for t in types) and (node.get("name") or node.get("telephone")):
                    address = node.get("address")
                    address_text = None
                    if isinstance(address, dict):
                        address_text = ", ".join(str(address.get(k)) for k in ("streetAddress", "addressLocality", "addressRegion") if address.get(k))
                    elif isinstance(address, str):
                        address_text = address
                    same_as = node.get("sameAs")
                    found = {
                        "name": node.get("name"), "telephone": node.get("telephone"), "email": node.get("email"),
                        "address": address_text or None, "same_as": [same_as] if isinstance(same_as, str) else list(same_as or []),
                    }
                    return
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                visit(json.loads(script.string or script.get_text() or ""))
            except (ValueError, TypeError):
                continue
        return found

    @staticmethod
    def _find_contact_page(soup: BeautifulSoup, base_url: str) -> str | None:
        base_host = (urlparse(base_url).hostname or "").removeprefix("www.")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            label = fold(anchor.get_text(" ", strip=True)) + " " + fold(href)
            if any(k in label for k in ("iletisim", "contact", "bize ulasin")):
                absolute = urljoin(base_url, href).split("#")[0]
                if (urlparse(absolute).hostname or "").removeprefix("www.") == base_host and not absolute.lower().endswith(SKIPPED_EXTENSIONS):
                    return absolute
        return None

    def _contact_page(self, client: httpx.Client, final_url: str, signals: WebsiteSignals) -> None:
        """İletişim sayfası ayrı bir adresteyse (footer dışında) telefon/e-posta/adres için bir kez okunur."""
        url = signals.contact_page_url
        if not url or url.rstrip("/") == final_url.rstrip("/"):
            signals.contact_page_fetched = False
            return
        try:
            status, page_url, headers, body = _open(client, "GET", url, timeout=REQUEST_TIMEOUT_SECONDS, read_body=True)
        except _Unreachable:
            signals.contact_page_fetched = False
            return
        if status != 200 or "html" not in (headers.get("content-type") or "text/html").lower():
            signals.contact_page_fetched = False
            return
        signals.contact_page_fetched = True
        soup = BeautifulSoup(body, "html.parser")
        anchors = soup.find_all("a", href=True)
        contact_schema = self._schema_business(soup)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        self._extract_contact_info([a for a in anchors if a.get("href")], text, signals, contact_schema)
        for network, domain in (("instagram", "instagram.com"), ("facebook", "facebook.com"), ("linkedin", "linkedin.com"), ("youtube", "youtube.com")):
            if network not in signals.social_links:
                link = next((a["href"] for a in anchors if domain in a["href"].lower()), None)
                if link:
                    signals.social_links[network] = link

    # ------------------------------------------------------------------ HTML ayrıştırma
    def _parse(self, soup: BeautifulSoup, final_url: str, signals: WebsiteSignals) -> None:
        html_tag = soup.find("html")
        signals.html_lang = (html_tag.get("lang") or None) if html_tag else None

        signals.title = (soup.title.get_text(strip=True) if soup.title else "") or None
        meta_desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        signals.meta_description = ((meta_desc.get("content") or "").strip() if meta_desc else "") or None
        signals.h1_texts = [h.get_text(" ", strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
        signals.h2_count = len(soup.find_all("h2"))
        signals.h3_count = len(soup.find_all("h3"))

        canonical = soup.find("link", attrs={"rel": lambda r: r and "canonical" in (r if isinstance(r, list) else [r])})
        signals.canonical = canonical.get("href") if canonical else None
        robots_meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
        signals.noindex = "noindex" in (robots_meta.get("content", "").lower() if robots_meta else "")
        signals.og_tags_present = soup.find("meta", attrs={"property": re.compile("^og:", re.I)}) is not None
        signals.favicon_present = soup.find("link", attrs={"rel": lambda r: r and any("icon" in x for x in (r if isinstance(r, list) else [r]))}) is not None
        signals.schema_types = _schema_types(soup)
        schema_business = self._schema_business(soup)  # betikler metin çıkarımında silinmeden ÖNCE okunmalı

        viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
        signals.viewport_ok = bool(viewport and "width=device-width" in (viewport.get("content", "").replace(" ", "").lower()))

        generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
        signals.generator = (generator.get("content") or None) if generator else None
        signals.script_count = len(soup.find_all("script", src=True))
        signals.stylesheet_count = len(soup.find_all("link", attrs={"rel": lambda r: r and "stylesheet" in (r if isinstance(r, list) else [r])}))

        images = soup.find_all("img")
        signals.images_total = len(images)
        signals.images_missing_alt = sum(1 for img in images if not (img.get("alt") or "").strip())

        raw_html = str(soup).lower()
        original_anchors = soup.find_all("a", href=True)  # büyük/küçük harf korunur (YouTube kanal kimliği gibi adresler harfe duyarlıdır)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        signals.word_count = len(text.split())
        signals.text_excerpt = text[:TEXT_EXCERPT_CHARS]
        signals.phone_in_text = bool(_PHONE_RE.search(text))
        signals.email_in_text = bool(_EMAIL_RE.search(text))
        signals.address_in_text = bool(_ADDRESS_RE.search(text))
        years = [int(m) for m in _COPYRIGHT_RE.findall(text + " " + raw_html[-3000:])]
        signals.copyright_year = max(years) if years else None

        anchors = BeautifulSoup(raw_html, "html.parser").find_all("a", href=True)
        hrefs = [a["href"].strip().lower() for a in anchors]
        signals.tel_link_present = any(h.startswith("tel:") for h in hrefs)
        signals.whatsapp_link_present = any(("wa.me" in h or "api.whatsapp.com" in h or "web.whatsapp.com" in h or h.startswith("whatsapp:")) for h in hrefs)
        signals.form_present = "<form" in raw_html
        signals.maps_link_present = any(
            m in raw_html for m in ("google.com/maps", "maps.google.", "maps.app.goo.gl", "goo.gl/maps", "maps/embed")
        )
        signals.social_links = {
            network: next((a["href"].strip() for a in original_anchors if domain in a["href"].lower()), None)
            for network, domain in {
                "instagram": "instagram.com", "facebook": "facebook.com", "youtube": "youtube.com",
                "twitter": "twitter.com", "x": "x.com", "linkedin": "linkedin.com", "tiktok": "tiktok.com",
            }.items()
        }
        signals.social_links = {k: v for k, v in signals.social_links.items() if v}

        # İçerik JavaScript ile mi çiziliyor? (statik HTML'de az metin + SPA/Wix işaretleri)
        generator_text = (signals.generator or "").lower()
        empty_root = bool(re.search(r'<div[^>]+id="(?:root|__next|app|__nuxt)"[^>]*>\s*</div>', raw_html)) or "__next_data__" in raw_html or "data-reactroot" in raw_html
        signals.js_rendered_hint = signals.word_count < 200 and ("wix" in generator_text or "wixstatic.com" in raw_html or empty_root or (signals.script_count or 0) >= 8)

        # Spam/yetişkin/bahis içeriği (site ele geçirilmiş olabilir): başlık, açıklama, H1 ve gövde metninde ara.
        visible = fold(" ".join(filter(None, [signals.title, signals.meta_description, " ".join(signals.h1_texts), signals.text_excerpt])))
        tokens = set(visible.split())
        signals.spam_terms = sorted({t for t in SPAM_TERMS if (t in tokens if " " not in t else t in visible)})

        # --- sitede görülen iletişim bilgileri (çapraz doğrulama için) ---
        self._extract_contact_info(original_anchors, text, signals, schema_business)
        signals.contact_page_url = self._find_contact_page(BeautifulSoup(raw_html, "html.parser"), final_url)

        folded_links = [(fold(a.get_text(" ", strip=True)) + " " + fold(a["href"])) for a in anchors]
        for attribute, keywords in _NAV_KEYWORDS.items():
            setattr(signals, attribute, any(k in link for link in folded_links for k in keywords))
        signals.has_shop_signals = any(marker in raw_html for marker in _ECOMMERCE_MARKERS)
        signals.agency_credit = find_agency_credit(soup, urlparse(final_url).netloc.lower().removeprefix("www."))

        # --- ölçüm/reklam altyapısı (yalnızca HTML'de görülen; görünmeyen bir etiketin YOKLUĞU kesin değildir → güven "orta") ---
        signals.analytics_tools = sorted(tool for tool, markers in _ANALYTICS_MARKERS.items() if any(m in raw_html for m in markers))
        signals.search_console_verified = soup_has_meta_verification(raw_html)
        signals.mailto_link_present = any(h.startswith("mailto:") for h in hrefs)
        signals.cta_present = any(word in fold(a.get_text(" ", strip=True)) for a in original_anchors for word in _CTA_WORDS) or any(
            word in fold(b.get_text(" ", strip=True)) for b in BeautifulSoup(raw_html, "html.parser").find_all("button") for word in _CTA_WORDS)
        host = urlparse(final_url).netloc.lower().removeprefix("www.")
        internal = {a["href"].split("#")[0] for a in original_anchors if a["href"].startswith("/") or (host and host in urlparse(a["href"]).netloc.lower())}
        signals.internal_links_count = len({h for h in internal if h and h != "/"})
