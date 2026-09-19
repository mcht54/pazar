"""Web arama motorları (Google Arama, Bing) — yalnızca ADAY üretir; hiçbir aday doğrulanmadan işletmeye bağlanmaz.

Bu ortamda ölçülen gerçek durum (2026-09-18):
- Google Arama: otomatik erişime CAPTCHA ("sıra dışı trafik") ile yanıt veriyor → ERİŞİLEMEDİ. Aşılmaya çalışılmaz.
- DuckDuckGo / Brave / Mojeek: bot doğrulaması / 403 → kullanılamaz.
- Bing: erişilebilir ama küçük yerel işletmelerde sıklıkla alakasız sonuç döndürür; bu yüzden sonuçlar yalnızca aday sayılır ve
  içerik doğrulamasından (ad + telefon/adres/şehir) geçmeden kabul edilmez.
"""

import base64
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlparse

import httpx
from bs4 import BeautifulSoup

from services.research.browser import (
    SourceBlocked,
    SourceError,
    browser_page,
    circuit_reason,
    detect_wall,
    polite_wait,
    source_lock,
    trip_circuit,
)

GOOGLE_SEARCH = "google_search"
BING_SEARCH = "bing_search"
GOOGLE_SEARCH_BREAKER_MINUTES = 6 * 60
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""


def _decode_bing_url(href: str) -> str:
    """Bing yönlendirme bağlantısından (bing.com/ck/a?...&u=a1<base64>) gerçek adresi çıkarır."""
    token = parse_qs(urlparse(href).query).get("u", [None])[0]
    if token and token.startswith("a1"):
        payload = token[2:]
        payload += "=" * (-len(payload) % 4)
        try:
            return base64.urlsafe_b64decode(payload).decode()
        except (ValueError, UnicodeDecodeError):
            return href
    return href


def parse_bing_results(html: str) -> list[SearchHit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: list[SearchHit] = []
    for item in soup.select("li.b_algo"):
        anchor = item.select_one("h2 a")
        if not anchor or not anchor.get("href"):
            continue
        snippet = item.select_one("p")
        hits.append(SearchHit(
            title=anchor.get_text(" ", strip=True), url=_decode_bing_url(anchor["href"]),
            snippet=snippet.get_text(" ", strip=True) if snippet else "", engine="bing",
        ))
    return hits


def bing_search(query: str) -> list[SearchHit]:
    """Bing web araması (tarayıcısız). Erişilemezse SourceError; engelse SourceBlocked."""
    reason = circuit_reason(BING_SEARCH)
    if reason:
        raise SourceBlocked(BING_SEARCH, reason)
    polite_wait(BING_SEARCH, 2.5)
    try:
        response = httpx.get(
            f"https://www.bing.com/search?q={quote(query)}&setlang=tr&cc=TR",
            headers={"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9"}, timeout=20, follow_redirects=True,
        )
    except httpx.RequestError as exc:
        raise SourceError(BING_SEARCH, f"Bing'e ulaşılamadı ({type(exc).__name__})") from exc
    if response.status_code in (403, 429) or "captcha" in response.text[:3000].lower():
        trip_circuit(BING_SEARCH, "Bing otomatik aramayı engelledi")
        raise SourceBlocked(BING_SEARCH, "Bing otomatik aramayı engelledi")
    if response.status_code != 200:
        raise SourceError(BING_SEARCH, f"Bing HTTP {response.status_code} döndürdü")
    return parse_bing_results(response.text)


# --------------------------------------------------------------------------- Google Arama
_google_probe: dict = {"at": 0.0, "status": None, "reason": None}


def google_search_status() -> tuple[str, str]:
    """Google Arama'ya otomatik erişim mümkün mü? Döndürür: ('erisilemedi'|'kontrol_edildi', açıklama).

    Sonuç süreç içinde 6 saat önbelleğe alınır: engelli bir kaynağa tekrar tekrar istek atmak IP itibarını (dolayısıyla Google
    Haritalar erişimini) de bozabilir. Erişilebilirse sonuçlar `google_search()` ile kullanılır.
    """
    reason = circuit_reason(GOOGLE_SEARCH)
    if reason:
        return "erisilemedi", f"Google Arama otomatik sorgulara izin vermiyor: {reason}. Engel aşılmaya çalışılmaz."
    if _google_probe["status"] == "kontrol_edildi" and time.time() - _google_probe["at"] < GOOGLE_SEARCH_BREAKER_MINUTES * 60:
        return "kontrol_edildi", "Google Arama erişilebilir."
    return "bilinmiyor", "Google Arama henüz denenmedi."


def google_search(query: str) -> list[SearchHit]:
    """Google web araması (tarayıcıyla). CAPTCHA görülürse SourceBlocked (6 saat devre kesici)."""
    reason = circuit_reason(GOOGLE_SEARCH)
    if reason:
        raise SourceBlocked(GOOGLE_SEARCH, reason)
    with source_lock(GOOGLE_SEARCH), browser_page() as page:
        polite_wait(GOOGLE_SEARCH, 5.0)
        page.goto(f"https://www.google.com/search?q={quote(query)}&hl=tr&gl=tr", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        wall = detect_wall(page)
        if wall:
            trip_circuit(GOOGLE_SEARCH, wall, minutes=GOOGLE_SEARCH_BREAKER_MINUTES)
            raise SourceBlocked(GOOGLE_SEARCH, wall)
        _google_probe.update(at=time.time(), status="kontrol_edildi", reason=None)
        hits: list[SearchHit] = []
        # Not: SERP yapısı bu ortamda (CAPTCHA nedeniyle) canlı doğrulanamadı; genel bir h3/bağlantı ayrıştırıcısıdır.
        for heading in page.locator("a h3").all()[:10]:
            anchor = heading.locator("xpath=ancestor::a[1]")
            href = anchor.get_attribute("href") if anchor.count() else None
            if href and href.startswith("http") and "google." not in urlparse(href).netloc:
                hits.append(SearchHit(title=heading.inner_text(), url=href, engine="google"))
        return hits
