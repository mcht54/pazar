"""Google API ayarları, hibrit veri katmanı (mevcut kaynakları bozmadan tamamlama + geri dönüş), hizmet matrisi, öncelik sıralaması."""

import httpx
import pytest
from bs4 import BeautifulSoup

from packages.config import settings
from packages.db.models import Business, SalesAssessment, SystemSetting
from services.auth.secrets_store import decrypt_secret
from services.hybrid import api_settings
from services.integrations.website_crawler.base import WebsiteSignals
from services.integrations.website_crawler.real_crawler import RealWebsiteCrawler
from services.research import google_api, pipeline
from services.research.browser import SourceError
from services.research.models import NOT_FOUND, SOURCE_BLOCKED, SOURCE_CHECKED, SOURCE_SKIPPED, VERIFIED, CONFLICTING, BusinessQuery, DirectoryProfile
from services.rule_engine.checks import build_gbp_checks, build_social_checks, build_website_checks
from services.rule_engine.priority import compute_priority, why_prospect
from services.rule_engine.scoring import compute_score
from services.rule_engine.service_matrix import LEVEL_LABELS, SECTOR_ONLY_POSSIBLE_LIMIT, build_service_matrix
from tests.conftest import make_user
from tests.test_rule_engine import ctx as _base_ctx, good_signals, google_business
from tests.test_sales_features import _analyzed_business

FAKE_KEY = "AIzaSyFAKE-KEY-FOR-TESTS-1234567890abcd"


def ctx(sector="İşitme Cihazı Merkezi", group="Sağlık ve Tıp", **kw):
    """Test bağlamı: sektör grubu ve Google Places kaynağı (GBP alanları ölçülebilir) ayarlanmış."""
    kw.setdefault("source", "google_places")
    context = _base_ctx(sector, group, **kw)
    context.sector_group = group
    return context


class _Resp:
    def __init__(self, status=200, text="{}"):
        self.status_code, self.text = status, text


@pytest.fixture(autouse=True)
def _no_real_google(monkeypatch):
    """Bu testlerde Google'a GERÇEK istek atılmaz: HTTP katmanı her zaman sahte/kapalı."""
    def boom(*a, **k):
        raise AssertionError("Testte gerçek Google HTTP isteği atılmamalı")
    monkeypatch.setattr(api_settings, "_http_post", boom)
    monkeypatch.setattr(google_api, "_post", boom)
    monkeypatch.setattr(settings, "google_places_api_key", "")


# ================================================================ API AYARLARI (yönetici)
def test_api_settings_initial_state_is_not_connected(client):
    s = client.get("/api/admin/api-settings/google").json()
    assert s["status"] == "not_connected" and s["status_icon"] == "🔴" and s["status_label"] == "Bağlı değil" and s["has_key"] is False and s["enabled"] is False


def test_saving_key_encrypts_it_and_never_returns_it(client, db):
    r = client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})
    assert r.status_code == 200
    state = r.json()
    assert state["has_key"] and state["status"] == "saved" and state["enabled"] is False
    assert FAKE_KEY not in r.text and FAKE_KEY not in client.get("/api/admin/api-settings/google").text, "anahtar arayüze açık gönderilmez"
    assert state["masked_key"].endswith(FAKE_KEY[-4:]) and "•" in state["masked_key"]
    row = db.get(SystemSetting, "google_api")
    assert FAKE_KEY not in (row.secret_encrypted or "") and decrypt_secret(row.secret_encrypted) == FAKE_KEY, "veritabanında şifreli saklanır"
    assert FAKE_KEY not in str(row.value)


def test_invalid_key_is_rejected_and_saving_does_not_call_google(client):
    assert client.put("/api/admin/api-settings/google/key", json={"api_key": "kisa"}).status_code == 422
    assert client.put("/api/admin/api-settings/google/key", json={"api_key": "a b " * 10}).status_code == 422
    assert client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY}).status_code == 200  # _http_post patlatılıyor: çağrılmadı


def test_test_connection_requires_key_and_success_enables_activation(client, db, monkeypatch):
    assert client.post("/api/admin/api-settings/google/test").status_code == 422
    client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})
    assert client.put("/api/admin/api-settings/google/enabled", json={"enabled": True}).status_code == 422, "test edilmeden aktifleştirilemez"
    calls = []
    monkeypatch.setattr(api_settings, "_http_post", lambda url, json, headers: (calls.append(headers["X-Goog-Api-Key"]) or _Resp(200, '{"places":[]}')))
    r = client.post("/api/admin/api-settings/google/test").json()
    assert r["ok"] is True and r["state"]["status"] == "connected" and calls == [FAKE_KEY] and FAKE_KEY not in str(r)
    assert api_settings.active_key(db) is None, "bağlantı başarılı ama henüz aktif değil → hat mevcut kaynaklarla çalışır"
    on = client.put("/api/admin/api-settings/google/enabled", json={"enabled": True}).json()
    assert on["status"] == "active" and on["status_icon"] == "✅" and api_settings.active_key(db) == FAKE_KEY
    off = client.put("/api/admin/api-settings/google/enabled", json={"enabled": False}).json()
    assert off["status"] == "connected" and api_settings.active_key(db) is None


@pytest.mark.parametrize("status,body,fragment", [(400, "API key not valid", "geçersiz"), (403, "Places API has not been used in project", "etkin değil"), (429, "quota", "sınır")])
def test_failed_connection_test_explains_in_turkish_and_never_activates(client, db, monkeypatch, status, body, fragment):
    client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})
    monkeypatch.setattr(api_settings, "_http_post", lambda url, json, headers: _Resp(status, body))
    r = client.post("/api/admin/api-settings/google/test").json()
    assert r["ok"] is False and fragment in r["message"] and r["state"]["status"] == "error" and r["state"]["enabled"] is False
    assert client.put("/api/admin/api-settings/google/enabled", json={"enabled": True}).status_code == 422


def test_network_error_during_test_is_reported(client, monkeypatch):
    client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})

    def down(url, json, headers):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(api_settings, "_http_post", down)
    r = client.post("/api/admin/api-settings/google/test").json()
    assert r["ok"] is False and "ulaşılamadı" in r["message"]


def test_removing_key_returns_to_not_connected(client, db, monkeypatch):
    client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})
    monkeypatch.setattr(api_settings, "_http_post", lambda url, json, headers: _Resp(200))
    client.post("/api/admin/api-settings/google/test")
    client.put("/api/admin/api-settings/google/enabled", json={"enabled": True})
    assert client.delete("/api/admin/api-settings/google/key").json()["status"] == "not_connected" and api_settings.active_key(db) is None


def test_new_key_resets_activation_and_test_result(client, db, monkeypatch):
    client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})
    monkeypatch.setattr(api_settings, "_http_post", lambda url, json, headers: _Resp(200))
    client.post("/api/admin/api-settings/google/test")
    client.put("/api/admin/api-settings/google/enabled", json={"enabled": True})
    s = client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY.replace("FAKE", "NEWK")}).json()
    assert s["status"] == "saved" and s["enabled"] is False and api_settings.active_key(db) is None


def test_environment_key_is_supported_without_exposing_it(client, monkeypatch):
    monkeypatch.setattr(settings, "google_places_api_key", FAKE_KEY)
    s = client.get("/api/admin/api-settings/google").json()
    assert s["has_key"] and s["key_source"] == "environment" and FAKE_KEY not in str(s)


def test_api_setting_changes_are_audited(client, db, monkeypatch):
    from packages.db.models import ActivityLog

    client.put("/api/admin/api-settings/google/key", json={"api_key": FAKE_KEY})
    monkeypatch.setattr(api_settings, "_http_post", lambda url, json, headers: _Resp(200))
    client.post("/api/admin/api-settings/google/test")
    client.put("/api/admin/api-settings/google/enabled", json={"enabled": True})
    logged = [a.action for a in db.query(ActivityLog).all()]
    assert {"api_settings_update", "api_test", "api_toggle"} <= set(logged)
    assert all(FAKE_KEY not in (a.detail or "") for a in db.query(ActivityLog).all()), "anahtar günlüğe yazılmaz"


# ================================================================ HİBRİT VERİ: mevcut kaynaklar + Google API
def _maps_profile(**kw) -> DirectoryProfile:
    base = dict(source="google_maps", name="Test İşletme", url="https://www.google.com/maps/place/Test", lat=40.77, lng=30.36, rating=None, review_count=None,
                category=None, address="Atatürk Cd. No:5 Serdivan Sakarya", phone="0264 111 22 33", website=None)
    base.update(kw)
    return DirectoryProfile(**base)


def _places_response(**over) -> dict:
    place = {"id": "PLACE1", "displayName": {"text": "Test İşletme"}, "formattedAddress": "Atatürk Cd. No:5 Serdivan Sakarya", "location": {"latitude": 40.77, "longitude": 30.36},
             "nationalPhoneNumber": "0264 111 22 33", "rating": 4.6, "userRatingCount": 87, "primaryTypeDisplayName": {"text": "İşitme cihazı mağazası"},
             "googleMapsUri": "https://maps.google.com/?cid=1", "regularOpeningHours": {"weekdayDescriptions": ["Pazartesi: 09:00 - 18:00"]}}
    place.update(over)
    return {"places": [place]}


def _run_research(monkeypatch, *, maps, api_json=None, api_error=None, key=FAKE_KEY):
    monkeypatch.setattr(pipeline.google_maps, "lookup", lambda *a, **k: (maps, [], "Google Haritalar eşleşti."))
    monkeypatch.setattr(pipeline.bing_maps, "lookup", lambda *a, **k: (None, "Bing'de eşleşme yok."))
    monkeypatch.setattr(pipeline, "bing_search", lambda q: [])
    monkeypatch.setattr(pipeline, "find_official_site", lambda *a, **k: (None, [], []))
    calls = []

    def fake_post(body, api_key):
        calls.append(api_key)
        if api_error:
            raise api_error
        return api_json
    monkeypatch.setattr(google_api, "_post", fake_post)
    query = BusinessQuery(name="Test İşletme", place_names=["Serdivan", "Sakarya"], lat=40.77, lng=30.36, phones=["2641112233"], address="Atatürk Cd. No:5 Serdivan Sakarya")
    result = pipeline.research_business(query, {}, crawler=object(), google_api_key=key)
    return result, calls


def _status(result, key):
    return next(s for s in result.sources if s.key == key)


def test_api_off_existing_sources_work_exactly_as_before(monkeypatch):
    result, calls = _run_research(monkeypatch, maps=_maps_profile(rating=4.8, review_count=120), key=None)
    assert calls == [] and _status(result, "google_api").status == SOURCE_SKIPPED and "bağlı/aktif değil" in _status(result, "google_api").detail
    assert result.verdicts["phone"].value == "0264 111 22 33" and result.verdicts["rating"].sources[0]["key"] == "google_maps" and result.google.rating == 4.8
    assert result.google_api is None


def test_api_agreeing_with_maps_adds_independent_confirmation_without_replacing_anything(monkeypatch):
    result, calls = _run_research(monkeypatch, maps=_maps_profile(rating=4.8, review_count=120, category="Hearing aid store"), api_json=_places_response())
    assert calls == [FAKE_KEY] and _status(result, "google_api").status == SOURCE_CHECKED
    phone = result.verdicts["phone"]
    assert phone.status == VERIFIED and {s["key"] for s in phone.sources} == {"google_maps", "google_api"}, "iki bağımsız kaynak birbirini doğruladı"
    assert result.google.rating == 4.8 and result.google.review_count == 120 and result.google.category == "Hearing aid store", "Maps'teki mevcut değerlerin üzerine YAZILMAZ"
    assert result.verdicts["rating"].sources[0]["key"] == "google_maps"


def test_api_conflict_is_shown_not_hidden(monkeypatch):
    result, _ = _run_research(monkeypatch, maps=_maps_profile(), api_json=_places_response(nationalPhoneNumber="0541 999 88 77"))
    phone = result.verdicts["phone"]
    assert phone.status == CONFLICTING and {s["key"] for s in phone.sources} == {"google_maps", "google_api"} and "farklı numara" in phone.note


def test_api_completes_fields_missing_from_maps_and_labels_the_source(monkeypatch):
    result, _ = _run_research(monkeypatch, maps=_maps_profile(rating=None, review_count=None, category=None, hours_text=None), api_json=_places_response())
    rating, reviews, hours = result.verdicts["rating"], result.verdicts["review_count"], result.verdicts["hours"]
    assert rating.value == "4,6" and rating.sources[0]["key"] == "google_api" and "tamamlandı" in rating.note
    assert reviews.value == "87" and reviews.sources[0]["key"] == "google_api" and hours.sources[0]["key"] == "google_api"
    assert result.verdicts["phone"].sources[0]["key"] in ("google_maps", "google_api")
    assert result.verdicts["phone"].to_dict()["source"] in ("google_maps", "google_api"), "alan bazlı kaynak bilgisi (source)"


def test_api_failure_falls_back_to_existing_system_and_analysis_continues(monkeypatch):
    baseline, _ = _run_research(monkeypatch, maps=_maps_profile(rating=4.8, review_count=120), key=None)
    failed, calls = _run_research(monkeypatch, maps=_maps_profile(rating=4.8, review_count=120), api_error=SourceError("google_api", "Google API HTTP 403 döndürdü"))
    assert calls == [FAKE_KEY] and _status(failed, "google_api").status == SOURCE_BLOCKED and "403" in _status(failed, "google_api").detail
    for key in ("phone", "address", "rating", "review_count", "name"):
        assert failed.verdicts[key].to_dict() == baseline.verdicts[key].to_dict(), f"{key}: API hatası mevcut sonucu değiştirmemeli"
    assert failed.google.rating == 4.8


def test_api_network_exception_also_falls_back(monkeypatch):
    def down(body, api_key):
        raise httpx.ConnectError("offline")
    result, _ = _run_research(monkeypatch, maps=_maps_profile(), api_json=None, api_error=httpx.ConnectError("offline"))
    assert _status(result, "google_api").status == SOURCE_BLOCKED and result.verdicts["phone"].value == "0264 111 22 33"


def test_maps_unavailable_but_api_available_uses_api_as_fallback_source(monkeypatch):
    result, _ = _run_research(monkeypatch, maps=None, api_json=_places_response())
    assert result.google is not None and result.google.source == "google_api" and result.google_api is None, "aynı veri iki kez sayılmaz"
    phone = result.verdicts["phone"]
    assert phone.value == "0264 111 22 33" and [s["key"] for s in phone.sources] == ["google_api"] and phone.status == VERIFIED
    assert result.verdicts["rating"].sources[0]["key"] == "google_api"


def test_no_data_anywhere_stays_unverified_never_invented(monkeypatch):
    result, _ = _run_research(monkeypatch, maps=None, api_json={"places": []})
    assert result.google is None and _status(result, "google_api").status == "eslesme_yok"
    assert result.verdicts["phone"].status == NOT_FOUND and result.verdicts["phone"].value is None and result.verdicts["phone"].to_dict()["source"] == "unknown"


def test_places_api_does_not_accept_a_different_business(monkeypatch):
    other = _places_response(displayName={"text": "Tamamen Başka Bir Firma"}, nationalPhoneNumber="0212 555 55 55", location={"latitude": 41.5, "longitude": 29.0},
                             formattedAddress="Başka Mah. Başka Sk. İstanbul")
    result, _ = _run_research(monkeypatch, maps=_maps_profile(), api_json=other)
    assert _status(result, "google_api").status == "eslesme_yok" and result.google_api is None


# ================================================================ YENİ WEB KONTROLLERİ
def test_crawler_detects_analytics_cta_internal_links():
    html = """<html><head><title>T</title><meta name="google-site-verification" content="x">
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script></head><body>
    <a href="/hizmetler">Hizmetler</a><a href="/iletisim">İletişim</a><a href="tel:+905321112233">Hemen Ara</a><a href="mailto:a@b.com">Mail</a></body></html>"""
    sig = WebsiteSignals(success=True)
    RealWebsiteCrawler()._parse(BeautifulSoup(html, "html.parser"), "https://example.com/", sig)
    assert sig.analytics_tools == ["ga4"] and sig.search_console_verified and sig.cta_present and sig.internal_links_count == 2 and sig.mailto_link_present


def test_crawler_does_not_invent_tracking_from_lookalike_text():
    sig = WebsiteSignals(success=True)
    RealWebsiteCrawler()._parse(BeautifulSoup("<html><body><p>quality-x gtm-ish</p><a href='/a'>a</a></body></html>", "html.parser"), "https://example.com/", sig)
    assert sig.analytics_tools == [] and sig.cta_present is False


def test_analytics_check_only_when_measured_and_never_when_js_rendered():
    context = ctx()
    assert "analytics" not in {c.key for c in build_website_checks(context, "https://kaya.example", good_signals())}, "ölçülmediyse 'yok' iddiası yapılmaz"
    problem = {c.key: c for c in build_website_checks(context, "https://kaya.example", good_signals(analytics_tools=[]))}["analytics"]
    assert problem.status == "problem" and problem.confidence == "medium" and "Ziyaretçi ölçümü" in problem.value
    ok = {c.key: c for c in build_website_checks(context, "https://kaya.example", good_signals(analytics_tools=["ga4", "gtm"]))}["analytics"]
    assert ok.status == "ok" and "Google Analytics 4" in ok.value
    js = {c.key: c for c in build_website_checks(context, "https://kaya.example", good_signals(analytics_tools=[], js_rendered_hint=True, word_count=50))}["analytics"]
    assert js.status == "unknown"


def test_peer_gap_check_uses_real_peer_counts_only():
    context = ctx()
    context.peer_web = {"has_services_page": (5, 6), "whatsapp_link_present": (4, 6), "has_blog": (1, 6)}
    checks = {c.key: c for c in build_website_checks(context, "https://kaya.example", good_signals(has_services_page=False, whatsapp_link_present=False, has_blog=False))}
    gap = checks["peer_gap"]
    assert gap.status == "problem" and "hizmet/ürün sayfaları (5/6 rakipte var)" in gap.detail and "WhatsApp" in gap.detail and "blog" not in gap.detail
    context.peer_web = {"has_services_page": (2, 2)}  # 3'ten az rakip ölçülmüş: karşılaştırma yapılmaz
    assert "peer_gap" not in {c.key for c in build_website_checks(context, "https://kaya.example", good_signals(has_services_page=False))} or \
        {c.key: c for c in build_website_checks(context, "https://kaya.example", good_signals(has_services_page=False))}["peer_gap"].status == "ok"


# ================================================================ HİZMET MATRİSİ
def _matrix(context, website="https://kaya.example", signals=None, business=None, **signal_overrides):
    base = dict(analytics_tools=["ga4"], cta_present=True, internal_links_count=12)
    base.update(signal_overrides)
    signals = signals if signals is not None else (good_signals(**base) if website else None)
    business = business or google_business(website=website)
    checks = build_website_checks(context, website, signals) + build_gbp_checks(context, business) + build_social_checks(context)
    return build_service_matrix(context, checks, business=business, signals=signals, has_website=bool(website)), checks


def _by_service(matrix):
    return {i["service"]: i for i in matrix["items"]}


def test_matrix_evaluates_every_mchttasarim_service_with_four_levels():
    matrix, _ = _matrix(ctx())
    names = {i["service"] for i in matrix["items"]}
    for expected in ("Web Tasarım", "Kurumsal Web Sitesi", "E-Ticaret", "Kurumsal SEO", "Yerel SEO", "Google İşletme Profili Optimizasyonu", "Google Ads", "Sosyal Medya Yönetimi",
                     "Sosyal Medya İçerik Üretimi", "Grafik Tasarım", "Kurumsal Kimlik", "Logo Tasarımı", "Matbaa", "Kartvizit", "Broşür", "Menü Baskı", "Katalog", "Davetiye",
                     "Branda Baskı", "Tabela", "Araç Giydirme", "Promosyon Ürünleri", "Fotoğraf ve Video İçerik"):
        assert expected in names, expected
    for item in matrix["items"]:
        assert item["level"] in LEVEL_LABELS and item["level_label"] == LEVEL_LABELS[item["level"]] and item["what"] and item["pitch"] and item["why"] and item["problem"]


def test_healthy_website_does_not_create_web_design_opportunity_but_other_opportunities_are_found():
    matrix, _ = _matrix(ctx(), analytics_tools=[])  # site sağlıklı ama ölçüm/reklam etiketi yok
    items = _by_service(matrix)
    assert items["Web Tasarım"]["level"] == "uygun_degil" and "sağlıklı" in items["Web Tasarım"]["not_applicable_reason"], "sırf site var diye Web Tasarım fırsatı üretilmez"
    assert items["Kurumsal Web Sitesi"]["level"] == "uygun_degil"
    ads = items["Google Ads"]
    assert ads["level"] == "satis" and ads["evidence"][0]["verified"] and "ölçümü" in ads["evidence"][0]["text"] and ads["caveat"] is None or ads["caveat"]
    assert matrix["counts"]["satis"] >= 1, "iyi siteli firmada bile satılabilir başka hizmet bulunmalı: sistem 'fırsat yok' dememeli"
    assert items["Tabela"]["level"] in ("olasi", "zayif") and items["Tabela"]["sector_only"] and "Tespit edilmedi" in items["Tabela"]["problem"], "kanıtsız fiziksel hizmet en fazla 'olası'"


def test_existing_google_ads_tag_means_ads_not_recommended():
    matrix, _ = _matrix(ctx(), analytics_tools=["ga4", "google_ads"])
    ads = _by_service(matrix)["Google Ads"]
    assert ads["level"] == "uygun_degil" and "Google Ads etiketi" in ads["not_applicable_reason"]


def test_unmeasured_tracking_never_becomes_verified_ads_opportunity():
    signals = good_signals()  # analytics_tools=None → ölçülmedi
    matrix, _ = _matrix(ctx(), signals=signals)
    ads = _by_service(matrix)["Google Ads"]
    assert ads["level"] in ("olasi", "zayif") and not ads["verified"] and ads["sector_only"], "kanıtsız Ads asla 🟢 olmaz"


def test_no_website_makes_corporate_site_green_and_redesign_not_applicable():
    matrix, _ = _matrix(ctx(), website=None, business=google_business(website=None))
    items = _by_service(matrix)
    assert items["Kurumsal Web Sitesi"]["level"] == "satis" and items["Kurumsal Web Sitesi"]["evidence"][0]["text"] == "Web sitesi bulunamadı"
    assert items["Web Tasarım"]["level"] == "uygun_degil" and items["Kurumsal SEO"]["level"] == "uygun_degil"
    assert matrix["items"][0]["service"] in ("Kurumsal Web Sitesi", "Yerel SEO"), "en güçlü fırsat en üstte"


def test_ecommerce_menu_catalog_are_sector_appropriate():
    clinic, _ = _matrix(ctx())
    assert _by_service(clinic)["E-Ticaret"]["level"] == "uygun_degil" and _by_service(clinic)["Menü Baskı"]["level"] == "uygun_degil"
    restaurant, _ = _matrix(ctx("Restoran", "Yeme-İçme", phrases=["restoran"]))
    assert _by_service(restaurant)["Menü Baskı"]["level"] in ("olasi", "zayif") and _by_service(restaurant)["Menü Baskı"]["sector_only"]
    shop, _ = _matrix(ctx("Mobilya", "Ev, Mobilya ve Dekorasyon", phrases=["mobilya"]))
    assert _by_service(shop)["E-Ticaret"]["level"] != "uygun_degil" and _by_service(shop)["Katalog"]["level"] != "uygun_degil"
    mover, _ = _matrix(ctx("Nakliyat", "Ulaşım ve Lojistik", phrases=["nakliyat"]))
    assert _by_service(mover)["Araç Giydirme"]["level"] != "uygun_degil" and _by_service(clinic)["Araç Giydirme"]["level"] == "uygun_degil"


@pytest.mark.parametrize("sector,group", [("İşitme Cihazı Merkezi", "Sağlık ve Tıp"), ("Restoran", "Yeme-İçme"), ("Mobilya", "Ev, Mobilya ve Dekorasyon"),
                                          ("Nakliyat", "Ulaşım ve Lojistik"), ("Hukuk Bürosu", "Profesyonel Hizmetler")])
@pytest.mark.parametrize("has_site", [True, False])
def test_no_green_opportunity_without_verified_evidence(sector, group, has_site):
    website = "https://kaya.example" if has_site else None
    matrix, _ = _matrix(ctx(sector, group, phrases=[sector.lower()]), website=website, business=google_business(website=website), analytics_tools=[])
    for item in matrix["items"]:
        if item["level"] == "satis":
            assert item["evidence"] and any(e["verified"] for e in item["evidence"]), (sector, item["service"])
        if item["sector_only"]:
            assert item["level"] != "satis" and "Tespit edilmedi" in item["problem"]
    assert sum(1 for i in matrix["items"] if i["level"] == "olasi" and i["sector_only"]) <= SECTOR_ONLY_POSSIBLE_LIMIT


def test_matrix_is_ordered_green_first_and_marks_primary():
    matrix, _ = _matrix(ctx(), website=None, business=google_business(website=None, photo_count=0, google_review_count=2))
    ranks = [{"satis": 3, "olasi": 2, "zayif": 1, "uygun_degil": 0}[i["level"]] for i in matrix["items"]]
    assert ranks == sorted(ranks, reverse=True)
    primaries = [i for i in matrix["items"] if i.get("primary")]
    assert primaries and primaries[0] is matrix["items"][0] and matrix["top"][0] == matrix["items"][0]["service"]


def test_score_groups_explain_the_score_line_by_line():
    context = ctx()
    signals = good_signals(analytics_tools=[], cta_present=False, whatsapp_link_present=False, meta_description=None, title="Ana Sayfa")
    checks = build_website_checks(context, "https://kaya.example", signals) + build_gbp_checks(context, google_business(photo_count=0, google_review_count=3))
    score = compute_score(checks, [])
    groups = score["groups"]
    assert groups and sum(g["points"] for g in groups) == score["score"], "grupların toplamı skora eşit"
    labels = {g["label"] for g in groups}
    assert {"Google Ads / ölçüm fırsatı", "Google İşletme eksikleri"} <= labels
    assert all(i["check_key"] and i["group"] for i in score["items"])


# ================================================================ ÖNCELİK SIRALAMASI
def _fake_matrix(*items):
    return {"items": [{"service": n, "level": lv, "sector_only": so, "commercial": c, "recurring": rec, "evidence": [], "evidence_weight": 0} for n, lv, so, c, rec in items]}


def test_priority_prefers_multi_service_potential_over_a_single_small_gap():
    small = compute_priority(score=90, matrix=_fake_matrix(("Kartvizit", "satis", False, 1, False)), completeness=0.9, has_phone=True)
    broad = compute_priority(score=82, matrix=_fake_matrix(("Web Tasarım", "satis", False, 5, False), ("Kurumsal SEO", "satis", False, 4, True), ("Google Ads", "satis", False, 4, True)),
                             completeness=0.9, has_phone=True)
    assert broad["value"] > small["value"], (broad["value"], small["value"])
    assert any("3 hizmette doğrulanmış satış fırsatı" in r for r in broad["reasons"]) and any("Ticari değeri yüksek" in r for r in broad["reasons"])
    assert any("Satış fırsatı skoru 82/100" in r for r in broad["reasons"])


def test_priority_penalizes_missing_phone_and_incomplete_analysis_but_stays_bounded():
    m = _fake_matrix(("Web Tasarım", "satis", False, 5, False))
    full = compute_priority(score=70, matrix=m, completeness=1.0, has_phone=True)
    partial = compute_priority(score=70, matrix=m, completeness=0.3, has_phone=False)
    assert partial["value"] < full["value"] and 0 <= partial["value"] <= full["value"] <= 100
    assert any("doğrulanamadı" in r for r in partial["reasons"])


def test_why_prospect_lists_only_evidence_based_findings():
    matrix, _ = _matrix(ctx(), analytics_tools=[])
    lines = why_prospect(matrix)
    assert lines and all(isinstance(x, str) and x for x in lines)
    assert any(x.startswith("Google Ads fırsatı tespit edildi") for x in lines)
    assert not any("Tespit edilmedi" in x for x in lines), "kanıtsız sektör olasılıkları 'neden potansiyel müşteri' listesine girmez"


# ================================================================ UÇTAN UCA: analiz → payload → API → sıralama
def test_analysis_payload_has_matrix_priority_and_why(client, db):
    bid = _analyzed_business(client, db, name="Matris Kliniği")
    d = client.get(f"/api/businesses/{bid}").json()
    a, b = d["assessment"], d["business"]
    assert a["service_matrix"]["items"] and a["priority"]["value"] is not None and a["priority"]["reasons"] and isinstance(a["why_prospect"], list)
    assert b["priority_score"] == a["priority"]["value"] and b["priority_reasons"] == a["priority"]["reasons"] and b["why_prospect"] == a["why_prospect"]
    assert b["primary_service"] == a["service_matrix"]["top"][0] or b["primary_service"] is None
    assert a["score"]["groups"], "skor dökümü gruplu"


def test_lists_and_dashboard_follow_priority_not_just_score(client, db):
    hi_score = _analyzed_business(client, db, name="Yüksek Skor Küçük Fırsat")
    broad = _analyzed_business(client, db, name="Geniş Fırsat Firması")

    def set_priority(bid, score, priority):
        row = db.query(SalesAssessment).filter_by(business_id=bid).order_by(SalesAssessment.id.desc()).first()
        payload = dict(row.payload)
        payload["priority"] = {**payload["priority"], "value": priority}
        payload["score"] = {**payload["score"], "score": score}
        row.payload = payload
        db.get(Business, bid).opportunity_score_total = score
        db.commit()

    set_priority(hi_score, 90, 64.0)
    set_priority(broad, 82, 89.0)
    order = [b["id"] for b in client.get("/api/businesses").json() if b["id"] in (hi_score, broad)]
    assert order == [broad, hi_score], "skor 82 ama geniş fırsatlı firma, skor 90 küçük fırsatlıdan önce gelmeli"
    today = [b["id"] for b in client.get("/api/dashboard/today?min_score=1&limit=50").json() if b["id"] in (hi_score, broad)]
    assert today == [broad, hi_score]
