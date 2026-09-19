"""Gerçek web sitesi analizörü: HTML ayrıştırma, erişim durumu sınıflandırma, güvenlik. Gerçek ağ çağrısı YOK."""

import pytest
from bs4 import BeautifulSoup

from services.integrations.website_crawler import real_crawler as rc
from services.integrations.website_crawler.base import WebsiteSignals
from services.integrations.website_crawler.real_crawler import RealWebsiteCrawler, _Unreachable

GOOD_HTML = """<!doctype html><html lang="tr"><head>
<title>Kaya İşitme Cihazları | Sakarya İşitme Merkezi</title>
<meta name="description" content="Sakarya'da işitme testi, işitme cihazı uygulaması ve bakım hizmeti sunan uzman odyolog kadrosu ile hizmetinizdeyiz.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="https://kaya.example/"><link rel="icon" href="/f.ico">
<meta property="og:title" content="Kaya">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"LocalBusiness","name":"Kaya"}</script>
</head><body>
<nav><a href="/hizmetler">Hizmetlerimiz</a><a href="/hakkimizda">Hakkımızda</a><a href="/referanslar">Referanslar</a><a href="/blog">Blog</a><a href="/iletisim">İletişim</a><a href="/randevu">Randevu Al</a></nav>
<h1>Sakarya İşitme Cihazı Merkezi</h1><h2>Hizmetler</h2><h3>Test</h3>
<p>{words}</p>
<a href="tel:+902640000000">0264 000 00 00</a> <a href="https://wa.me/902640000000">WhatsApp</a>
<a href="https://instagram.com/kaya">ig</a><a href="https://facebook.com/kaya">fb</a>
<iframe src="https://www.google.com/maps/embed?pb=1"></iframe><form action="/gonder"></form>
<img src="a.jpg" alt="Klinik"><img src="b.jpg" alt="Cihaz">
<footer>© 2026 Kaya İşitme</footer></body></html>""".replace("{words}", "işitme " * 200)

BAD_HTML = """<html><head><title>Ana Sayfa</title></head><body><div id="root"></div>
<img src="a.jpg"><img src="b.jpg"><img src="c.jpg"><img src="d.jpg"><img src="e.jpg"><img src="f.jpg">
<p>Merhaba</p><footer>© 2016</footer></body></html>"""


def _parse(html: str, url: str = "https://kaya.example/") -> WebsiteSignals:
    signals = WebsiteSignals(success=True, final_url=url)
    RealWebsiteCrawler()._parse(BeautifulSoup(html, "html.parser"), url, signals)
    return signals


def test_parse_good_page_extracts_real_measurements():
    s = _parse(GOOD_HTML)
    assert s.title == "Kaya İşitme Cihazları | Sakarya İşitme Merkezi"
    assert s.meta_description.startswith("Sakarya'da işitme testi")
    assert s.h1_texts == ["Sakarya İşitme Cihazı Merkezi"]
    assert s.h2_count == 1 and s.h3_count == 1
    assert s.viewport_ok is True
    assert s.tel_link_present is True and s.whatsapp_link_present is True
    assert s.maps_link_present is True and s.form_present is True
    assert set(s.social_links) == {"instagram", "facebook"}
    assert "LocalBusiness" in s.schema_types
    assert s.has_services_page and s.has_about_page and s.has_references_page and s.has_blog and s.has_contact_page and s.has_appointment_link
    assert s.images_total == 2 and s.images_missing_alt == 0
    assert s.copyright_year == 2026
    assert s.canonical == "https://kaya.example/" and s.noindex is False and s.og_tags_present is True and s.favicon_present is True
    assert s.js_rendered_hint is False
    assert s.spam_terms == []


def test_parse_bad_page_reports_missing_things_as_false_not_none():
    s = _parse(BAD_HTML)
    assert s.title == "Ana Sayfa"
    assert s.meta_description is None
    assert s.h1_texts == []
    assert s.viewport_ok is False
    assert s.tel_link_present is False and s.whatsapp_link_present is False and s.maps_link_present is False
    assert s.images_total == 6 and s.images_missing_alt == 6
    assert s.copyright_year == 2016
    assert s.js_rendered_hint is True, "boş #root + az metin: içerik JavaScript ile çiziliyor olabilir"


def test_parse_detects_noindex_and_spam_content():
    html = '<html><head><title>Bokep Indonesia Terbaru</title><meta name="robots" content="noindex,follow"></head><body><h1>Bahis Casino</h1></body></html>'
    s = _parse(html)
    assert s.noindex is True
    assert "bokep" in s.spam_terms and "bahis" in s.spam_terms and "casino" in s.spam_terms


def test_internal_links_skip_cloudflare_internal_paths_files_and_external():
    soup = BeautifulSoup(
        '<a href="/cdn-cgi/l/email-protection">e</a><a href="/a.pdf">p</a><a href="https://other.com/x">o</a>'
        '<a href="/hizmet">h</a><a href="/hizmet">dup</a><a href="mailto:a@b.c">m</a><a href="#top">t</a>',
        "html.parser",
    )
    assert RealWebsiteCrawler._internal_links(soup, "https://kaya.example/") == ["https://kaya.example/hizmet"]


def test_normalize_url_variants():
    assert rc._normalize_url("kaya.example") == "https://kaya.example"
    assert rc._normalize_url("a.com;b.com") == "https://a.com"
    assert rc._normalize_url("ftp://a.com") is None
    assert rc._normalize_url("localhost") is None
    assert rc._normalize_url("") is None


def test_social_and_google_addresses_are_not_websites():
    s = RealWebsiteCrawler().analyze("https://www.instagram.com/isletme")
    assert s.success is False and s.outcome == "not_a_website"
    assert "sosyal medya" in s.error_reason
    assert rc._classify_listing("https://sites.google.com/view/x") is None, "Google Sites gerçek bir site kurucusudur"
    assert rc._classify_listing("https://www.google.com/maps/place/x") is not None


def test_private_network_addresses_are_never_fetched():
    """SSRF koruması: OSM/Google'dan gelen adres iç ağa işaret ediyorsa istek atılmaz."""
    for url in ("http://127.0.0.1/", "http://localhost.localdomain/", "http://192.168.1.10/admin", "http://10.0.0.5/"):
        with pytest.raises(_Unreachable) as exc:
            rc._ensure_public(url)
        assert exc.value.kind in ("private", "dns")
    s = RealWebsiteCrawler().analyze("http://127.0.0.1:8000/api/health")
    assert s.success is False and s.outcome == "unreachable"


def _analyze_with_fake_open(monkeypatch, fake_open):
    monkeypatch.setattr(rc, "_open", fake_open)
    monkeypatch.setattr(rc, "_ensure_public", lambda url: None)
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    monkeypatch.setattr(RealWebsiteCrawler, "_pagespeed", lambda self, url: (None, "test"))
    return RealWebsiteCrawler().analyze("https://kaya.example")


class _H(dict):
    def get(self, k, d=None):
        return super().get(k.lower(), d)


def test_bot_protection_is_reported_as_blocked_not_as_broken_site(monkeypatch):
    def fake_open(client, method, url, **kw):
        if url.endswith("robots.txt"):
            return 404, url, _H(), b""
        return 403, url, _H({"server": "cloudflare"}), b"Attention Required! | Cloudflare"

    s = _analyze_with_fake_open(monkeypatch, fake_open)
    assert s.success is False and s.outcome == "blocked"
    assert "bot" in s.error_reason.lower()


def test_robots_disallow_is_respected(monkeypatch):
    def fake_open(client, method, url, **kw):
        if url.endswith("robots.txt"):
            return 200, url, _H(), b"User-agent: *\nDisallow: /\n"
        raise AssertionError("robots.txt izin vermiyorsa ana sayfa AÇILMAMALI")

    s = _analyze_with_fake_open(monkeypatch, fake_open)
    assert s.outcome == "robots_disallowed" and s.success is False


def test_dns_failure_and_404_are_classified_as_permanent(monkeypatch):
    def dns_open(client, method, url, **kw):
        if url.endswith("robots.txt"):
            raise _Unreachable("dns", kind="dns")
        raise _Unreachable("Alan adı çözümlenemedi", kind="dns")

    s = _analyze_with_fake_open(monkeypatch, dns_open)
    assert s.outcome == "unreachable" and s.failure_kind == "dns"

    def notfound_open(client, method, url, **kw):
        if url.endswith("robots.txt"):
            return 404, url, _H(), b""
        return 404, url, _H({"content-type": "text/html"}), b"nope"

    s = _analyze_with_fake_open(monkeypatch, notfound_open)
    assert s.outcome == "unreachable" and s.failure_kind == "http_404"


def test_successful_fetch_end_to_end_with_fake_network(monkeypatch):
    def fake_open(client, method, url, **kw):
        if url.endswith("robots.txt"):
            return 200, url, _H(), b"User-agent: *\nAllow: /\nSitemap: https://kaya.example/sm.xml\n"
        if url.endswith("sm.xml"):
            return 200, url, _H(), b""
        if url in ("https://kaya.example", "https://kaya.example/"):
            return 200, "https://kaya.example/", _H({"content-type": "text/html; charset=utf-8"}), GOOD_HTML.encode("utf-8")
        if url.endswith("/blog"):
            return 404, url, _H(), b""
        return 200, url, _H(), b""

    s = _analyze_with_fake_open(monkeypatch, fake_open)
    assert s.success and s.outcome == "ok" and s.https_enabled is True
    assert s.sitemap_present is True
    assert s.links_checked >= 5
    assert [b["url"] for b in s.broken_links] == ["https://kaya.example/blog"]
    assert s.pagespeed is None and s.pagespeed_error == "test"


def test_pagespeed_is_unverified_without_key(monkeypatch):
    monkeypatch.setattr(rc.settings, "google_pagespeed_api_key", "")
    assert RealWebsiteCrawler()._pagespeed("https://a.com") == (None, "Google PageSpeed API anahtarı tanımlı değil")
