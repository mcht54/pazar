"""Tarayıcı tabanlı kaynaklar (Google Haritalar, Bing Haritalar, Google Arama) için ortak altyapı.

Kurallar:
- Gerçek bir Chromium açılır ve sayfa bir kullanıcı gibi okunur; resmi API kullanılmaz.
- Kibar olma: aynı kaynağa art arda istekler arasında minimum bekleme uygulanır ve aynı anda tek oturum açılır.
- ENGEL AŞILMAZ: CAPTCHA / "olağandışı trafik" / consent duvarı görülürse istek durdurulur, kaynak bir süre
  "ERİŞİLEMEDİ" işaretlenir (devre kesici). Gizlenme/stealth eklentisi, proxy ya da CAPTCHA çözümü YOKTUR.
- Erişilemeyen kaynağın verisi asla tahmin edilmez.
"""

import random
import threading
import time
from contextlib import contextmanager

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
NAVIGATION_TIMEOUT_MS = 30000
DEFAULT_MIN_INTERVAL_SECONDS = 4.0
BREAKER_MINUTES = 30


class SourceBlocked(Exception):
    """Kaynak otomatik erişimi engelledi (CAPTCHA/consent/sıra dışı trafik)."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


class SourceError(Exception):
    """Kaynak açılmadı/yapısı beklenenden farklı (engel değil, teknik sorun)."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


_state_lock = threading.Lock()
_source_locks: dict[str, threading.Lock] = {}
_last_request_at: dict[str, float] = {}
_blocked_until: dict[str, tuple[float, str]] = {}


def source_lock(source: str) -> threading.Lock:
    with _state_lock:
        return _source_locks.setdefault(source, threading.Lock())


def circuit_reason(source: str) -> str | None:
    """Devre açıksa (kaynak yakın zamanda engelledi) nedenini, değilse None döndürür."""
    with _state_lock:
        entry = _blocked_until.get(source)
        if entry and entry[0] > time.time():
            return entry[1]
        if entry:
            _blocked_until.pop(source, None)
    return None


def trip_circuit(source: str, reason: str, minutes: float = BREAKER_MINUTES) -> None:
    with _state_lock:
        _blocked_until[source] = (time.time() + minutes * 60, reason)


def reset_circuits() -> None:
    """Testler ve elle yeniden deneme için."""
    with _state_lock:
        _blocked_until.clear()
        _last_request_at.clear()


def polite_wait(source: str, min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS) -> None:
    """Kaynağa yapılan iki istek arasında en az min_interval (+ küçük rastgele pay) bekler."""
    with _state_lock:
        last = _last_request_at.get(source, 0.0)
    wait = min_interval + random.uniform(0, 1.2) - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    with _state_lock:
        _last_request_at[source] = time.monotonic()


@contextmanager
def browser_page(*, viewport=(1400, 1000)):
    """Tek kullanımlık Chromium sayfası (tr-TR). Çağıran, kaynak kilidini kendisi tutmalıdır."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="tr-TR", user_agent=USER_AGENT, viewport={"width": viewport[0], "height": viewport[1]})
            page = context.new_page()
            page.set_default_timeout(15000)
            yield page
        finally:
            browser.close()


_WALL_TEXT = ("olağandışı trafik", "sıra dışı bir trafik", "unusual traffic", "not a robot", "bot olmadığınız", "captcha", "select all squares")


def detect_wall(page) -> str | None:
    """Sayfa bir engel/consent duvarı mı? Döndürür: neden metni ya da None."""
    url = page.url or ""
    if "consent.google" in url or "consent.youtube" in url:
        return "Google onay (consent) duvarı"
    if "/sorry/" in url:
        return "CAPTCHA / sıra dışı trafik uyarısı"
    try:
        body = page.inner_text("body", timeout=2500).lower()
    except (PlaywrightError, PlaywrightTimeout):
        return None
    if any(marker in body[:1500] for marker in _WALL_TEXT):
        return "bot doğrulaması (CAPTCHA) isteniyor"
    return None


def guarded_goto(page, url: str, source: str, *, wait_ms: int = 2500, min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS) -> None:
    """Kibar bekleme + gezinme + engel denetimi. Engel görülürse devre kesiciyi açıp SourceBlocked fırlatır."""
    reason = circuit_reason(source)
    if reason:
        raise SourceBlocked(source, reason)
    polite_wait(source, min_interval)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    except PlaywrightTimeout as exc:
        raise SourceError(source, "sayfa zaman aşımına uğradı") from exc
    except PlaywrightError as exc:
        raise SourceError(source, f"sayfa açılamadı ({str(exc)[:80]})") from exc
    page.wait_for_timeout(wait_ms)
    wall = detect_wall(page)
    if wall:
        trip_circuit(source, wall)
        raise SourceBlocked(source, wall)
