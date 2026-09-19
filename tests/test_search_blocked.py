"""Google Arama engeli (CAPTCHA): engel AŞILMAZ, kaynak ERİŞİLEMEDİ kalır, hiçbir değer uydurulmaz."""

from contextlib import contextmanager

import pytest

from services.research import pipeline, web_search
from services.research.browser import SourceBlocked, detect_wall, reset_circuits
from services.research.models import NOT_FOUND, SOURCE_BLOCKED, BusinessQuery


class CaptchaPage:
    """Google'ın 'sıra dışı trafik' sayfasını taklit eder. Yalnızca gezinme/okuma yapılabilir; başka her etkileşim (tıklama, form doldurma,
    yeniden deneme, script çalıştırma…) engeli aşma girişimi sayılır ve testi düşürür."""

    url = "https://www.google.com/sorry/index?continue=https://www.google.com/search"
    ALLOWED = {"goto", "wait_for_timeout", "inner_text"}

    def __init__(self):
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name not in self.ALLOWED:
            raise AssertionError(f"Engel sayfasında izin verilmeyen etkileşim: page.{name}() — CAPTCHA aşılmaya çalışılmamalı")
        def method(*args, **kwargs):
            self.calls.append(name)
            return "Sıra dışı bir trafik algıladık. Bir robot olmadığınızı doğrulayın." if name == "inner_text" else None
        return method


@pytest.fixture
def blocked_google(monkeypatch):
    reset_circuits()
    opened: list[CaptchaPage] = []

    @contextmanager
    def fake_browser_page(**_):
        page = CaptchaPage()
        opened.append(page)
        yield page

    monkeypatch.setattr(web_search, "browser_page", fake_browser_page)
    monkeypatch.setattr(web_search, "polite_wait", lambda *a, **k: None)
    yield opened
    reset_circuits()


def test_detect_wall_recognises_captcha_and_consent_pages():
    class P:
        def __init__(self, url, body=""):
            self.url, self._body = url, body

        def inner_text(self, *_a, **_k):
            return self._body

    assert detect_wall(P("https://www.google.com/sorry/index")) is not None
    assert detect_wall(P("https://consent.google.com/m?continue=x")) is not None
    assert detect_wall(P("https://www.google.com/search?q=x", "Olağandışı trafik algılandı")) is not None
    assert detect_wall(P("https://www.google.com/search?q=x", "İşitme cihazı Adapazarı - Google Arama sonuçları")) is None


def test_google_search_stops_at_captcha_and_never_touches_the_page_further(blocked_google):
    with pytest.raises(SourceBlocked) as first:
        web_search.google_search("işitme cihazı Adapazarı")
    assert "CAPTCHA" in first.value.reason or "sıra dışı" in first.value.reason.lower()
    page = blocked_google[0]
    assert page.calls.count("goto") == 1, f"engelden sonra sayfa yeniden denenmemeli: {page.calls}"
    assert set(page.calls) <= {"goto", "wait_for_timeout", "inner_text"}, f"yalnızca gezinme/bekleme/okuma yapılmalı: {page.calls}"


def test_circuit_breaker_prevents_hammering_a_blocked_google(blocked_google):
    with pytest.raises(SourceBlocked):
        web_search.google_search("ilk sorgu")
    assert len(blocked_google) == 1
    for _ in range(3):  # sonraki sorgular tarayıcı bile açmadan reddedilir (IP itibarını daha fazla bozmamak için)
        with pytest.raises(SourceBlocked):
            web_search.google_search("tekrar")
    assert len(blocked_google) == 1, "engelden sonra Google'a yeni istek atılmamalı"


def test_status_reports_erisilemedi_and_states_no_bypass(blocked_google):
    with pytest.raises(SourceBlocked):
        web_search.google_search("x")
    state, detail = web_search.google_search_status()
    assert state == "erisilemedi" and "aşılmaya çalışılmaz" in detail


def test_pipeline_shows_google_search_as_erisilemedi_and_invents_no_website(blocked_google, monkeypatch):
    monkeypatch.setattr(pipeline.google_maps, "lookup", lambda *a, **k: (None, [], "Google Haritalar'da eşleşen kayıt bulunamadı."))
    monkeypatch.setattr(pipeline.bing_maps, "lookup", lambda *a, **k: (None, "Bing Haritalar'da eşleşen kayıt bulunamadı."))
    monkeypatch.setattr(pipeline, "bing_search", lambda q: [])  # Bing de sonuç vermiyor
    searched = []

    def fake_find(query, known_sites, phones, address, *, crawler, extra_urls, search_fn):
        searched.append(search_fn("Test İşletme Sakarya"))  # Google engelli → Bing'e düşer, boş döner
        return None, [], []

    monkeypatch.setattr(pipeline, "find_official_site", fake_find)
    query = BusinessQuery(name="Test İşletme", place_names=["Serdivan", "Sakarya"], lat=None, lng=None)
    result = pipeline.research_business(query, {}, crawler=object(), use_google=True)

    google_search_status = next(s for s in result.sources if s.key == "google_search")
    assert google_search_status.status == SOURCE_BLOCKED, "Google Arama ERİŞİLEMEDİ olarak gösterilmeli"
    assert "aşılmaya çalışılmaz" in google_search_status.detail
    assert searched == [[]], "engelli Google'dan sonuç uydurulmamalı"
    assert result.site is None and result.candidates == []
    website = result.verdicts["website"]
    assert website.status == NOT_FOUND and not website.value, "doğrulanamayan web sitesi tahmin edilmemeli"
    assert len(blocked_google) == 1, "arama boyunca Google'a tek deneme yapılmalı"
