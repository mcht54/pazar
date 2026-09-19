"""Kontroller (web sitesi + Google profili) ve satış değerlendirmesi — saf fonksiyon testleri (DB/ağ yok)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.integrations.website_crawler.base import WebsiteSignals
from services.rule_engine.checks import (
    SVC_CORPORATE_SITE,
    SVC_ECOM,
    SVC_GBP,
    SVC_SEO,
    SVC_SOCIAL,
    SVC_WEB,
    AnalysisContext,
    build_gbp_checks,
    build_website_checks,
    mentions,
)
from services.rule_engine.sales import assess
from services.rule_engine.sector_profiles import get_sector_profile

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def ctx(sector="İşitme Cihazı Merkezi", group="Sağlık ve Tıp", source="google_maps", phrases=None, peers=None, name="Kaya İşitme"):
    return AnalysisContext(
        business_name=name,
        sector_name=sector,
        profile=get_sector_profile(sector, group),
        sector_phrases=phrases or ["işitme cihazı", "işitme merkezi"],
        place_names=["Adapazarı", "Sakarya"],
        source=source,
        now=NOW,
        peer_review_counts=peers or [],
    )


def good_signals(**overrides) -> WebsiteSignals:
    base = dict(
        success=True, outcome="ok", requested_url="https://kaya.example", final_url="https://kaya.example/", http_status=200,
        https_enabled=True, response_ms=600.0, html_bytes=60_000, title="Kaya İşitme Cihazı Merkezi Adapazarı | Sakarya",
        meta_description="Adapazarı'nda işitme testi, işitme cihazı uygulaması ve bakım hizmeti sunan uzman odyolog kadrosu ile hizmetinizdeyiz.",
        h1_texts=["İşitme Cihazı Merkezi"], h2_count=3, h3_count=2, canonical="https://kaya.example/", noindex=False,
        og_tags_present=True, favicon_present=True, schema_types=["LocalBusiness"], viewport_ok=True, word_count=600,
        text_excerpt="Adapazarı işitme cihazı merkezi", images_total=10, images_missing_alt=0, copyright_year=2026,
        js_rendered_hint=False, tel_link_present=True, whatsapp_link_present=True, maps_link_present=True, form_present=True,
        phone_in_text=True, email_in_text=True, address_in_text=True, social_links={"instagram": "https://instagram.com/x"},
        has_services_page=True, has_about_page=True, has_references_page=True, has_blog=True, has_contact_page=True,
        has_appointment_link=True, has_shop_signals=False, sitemap_present=True, links_checked=5, broken_links=[],
    )
    base.update(overrides)
    return WebsiteSignals(**base)


def by_key(checks):
    return {c.key: c for c in checks}


def listing_business(**kw):
    base = dict(source_profile={}, category_label="İşitme Cihazı Merkezi", phone=None, website=None, opening_hours=None,
                photo_count=None, google_review_count=None, google_rating=None, last_review_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def google_business(**kw):
    base = dict(
        source_profile={"types": ["hearing_aid_store", "audiologist", "store", "health"], "primary_type": "hearing_aid_store", "photos_capped": False, "reviews_sampled": 5, "business_status": "OPERATIONAL"},
        category_label="İşitme cihazı mağazası", phone="0264 000 00 00", website="https://kaya.example", opening_hours="Pzt: 09:00-18:00",
        photo_count=25, google_review_count=120, google_rating=4.7, last_review_at=NOW - timedelta(days=10),
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ================================================================ WEB SİTESİ
def test_strong_website_has_no_problems():
    checks = build_website_checks(ctx(), "https://kaya.example", good_signals())
    problems = [c for c in checks if c.status == "problem"]
    assert problems == [], [p.value for p in problems]


def test_no_website_without_google_profile_is_medium_confidence_and_needs_verification():
    (check,) = build_website_checks(ctx(source="google_maps"), None, None)
    assert check.status == "problem" and check.value == "Web sitesi bulunamadı"
    assert check.confidence == "medium" and check.needs_verification is True
    assert check.services == (SVC_CORPORATE_SITE,)
    assert "Google Haritalar profili okunamadığı için doğrulanamadı" in check.detail


def test_no_website_from_google_is_high_confidence():
    (check,) = build_website_checks(ctx(source="google_places"), None, None)
    assert check.confidence == "high" and check.needs_verification is False
    assert "Google İşletme Profilinde" in check.detail


def test_unreachable_website_is_not_analyzed_and_says_so():
    s = WebsiteSignals(success=False, outcome="unreachable", failure_kind="timeout", error_reason="Site yanıt vermedi (zaman aşımı)")
    checks = build_website_checks(ctx(), "https://kaya.example", s)
    assert [c.key for c in checks] == ["presence", "access"], "erişilemeyen sitede başka hiçbir kontrol uydurulmamalı"
    access = checks[1]
    assert access.status == "unknown", "geçici erişim hatası (timeout) sorun sayılmaz"
    assert "analiz edilemedi" in access.value.lower() and "erişim hatası" in access.value.lower()


def test_permanently_dead_site_is_a_problem_but_needs_verification():
    s = WebsiteSignals(success=False, outcome="unreachable", failure_kind="dns", error_reason="Alan adı çözümlenemedi")
    access = by_key(build_website_checks(ctx(), "https://x.example", s))["access"]
    assert access.status == "problem" and access.severity == "high" and access.confidence == "medium"
    assert access.needs_verification is True
    assert SVC_CORPORATE_SITE in access.services


def test_bot_blocked_and_robots_are_unknown_not_problems():
    for outcome in ("blocked", "robots_disallowed"):
        s = WebsiteSignals(success=False, outcome=outcome, error_reason="x")
        access = by_key(build_website_checks(ctx(), "https://x.example", s))["access"]
        assert access.status == "unknown" and access.severity == "none"


def test_instagram_as_website_is_flagged_as_missing_corporate_site():
    s = WebsiteSignals(success=False, outcome="not_a_website", error_reason="Web sitesi alanında gerçek bir site yerine sosyal medya/mesajlaşma adresi (instagram.com) girilmiş")
    presence = by_key(build_website_checks(ctx(), "https://instagram.com/x", s))["presence"]
    assert presence.status == "problem" and "instagram" in presence.detail
    assert presence.services == (SVC_CORPORATE_SITE,)


def test_title_problem_is_specific_not_generic():
    s = good_signals(title="Ana Sayfa")
    checks = by_key(build_website_checks(ctx(), "https://kaya.example", s))
    assert checks["title"].status == "problem"
    assert '"Ana Sayfa"' in checks["title"].detail, "kanıt: gerçek title metni gösterilmeli"
    kw = checks["title_keywords"]
    assert kw.status == "problem"
    assert kw.value == "Title etiketi yetersiz: ana hizmet ve şehir/ilçe bilgisi bulunmuyor"
    assert kw.services == (SVC_SEO, "Yerel SEO"), "şehir bilgisi eksikse yerel SEO da satılabilir"
    assert "işitme cihazı" in kw.detail and "Adapazarı" in kw.detail


def test_missing_meta_h1_are_seo_findings_with_service_and_reason():
    s = good_signals(meta_description=None, h1_texts=[])
    checks = by_key(build_website_checks(ctx(), "https://kaya.example", s))
    for key in ("meta_description", "h1"):
        c = checks[key]
        assert c.status == "problem" and c.services == (SVC_SEO,) and c.why and c.detail


def test_mobile_check_is_honest_about_being_a_proxy():
    bad = by_key(build_website_checks(ctx(), "https://kaya.example", good_signals(viewport_ok=False)))["mobile"]
    assert bad.status == "problem" and bad.services == (SVC_WEB,)
    assert "gerçek cihaz testi yapılmadı" in bad.detail
    ok = by_key(build_website_checks(ctx(), "https://kaya.example", good_signals()))["mobile"]
    assert ok.status == "ok" and "gerçek cihaz testi yapılmadı" in ok.value


def test_speed_without_pagespeed_is_labeled_approximate():
    slow = by_key(build_website_checks(ctx(), "https://kaya.example", good_signals(response_ms=4200)))["speed"]
    assert slow.status == "problem" and "yaklaşık" in slow.detail
    with_ps = by_key(build_website_checks(ctx(), "https://kaya.example", good_signals(pagespeed={"performance_score": 32})))["speed"]
    assert with_ps.status == "problem" and with_ps.severity == "high" and with_ps.source == "pagespeed"


def test_js_rendered_sites_do_not_get_false_content_findings():
    s = good_signals(js_rendered_hint=True, word_count=40, h1_texts=[], h2_count=0, text_excerpt="")
    checks = by_key(build_website_checks(ctx(), "https://kaya.example", s))
    for key in ("h1", "content_volume", "heading_structure"):
        assert checks[key].status == "unknown", f"{key}: JavaScript ile çizilen sitede ölçülemeyen alan sorun sayılmamalı"


def test_spam_content_is_a_high_severity_finding():
    s = good_signals(title="Bokep Indonesia Terbaru", spam_terms=["bokep"])
    c = by_key(build_website_checks(ctx(), "https://kaya.example", s))["spam_content"]
    assert c.status == "problem" and c.severity == "high" and c.confidence == "high"
    assert "ele geçirilmiş" in c.value


def test_brand_mismatch_flagged_only_when_name_absent():
    ok = build_website_checks(ctx(name="Kaya İşitme"), "https://kaya.example", good_signals(text_excerpt="Kaya İşitme Merkezi hakkında"))
    assert "brand_match" not in by_key(ok)
    bad = build_website_checks(ctx(name="Zeytinburnu Optik"), "https://kaya.example", good_signals(title="Başka Firma", meta_description="x", h1_texts=["Başka"], text_excerpt="hiçbiri"))
    assert by_key(bad)["brand_match"].status == "problem"


def test_conversion_points_counting():
    none = good_signals(tel_link_present=False, whatsapp_link_present=False, form_present=False, has_appointment_link=False, email_in_text=False, phone_in_text=False)
    assert by_key(build_website_checks(ctx(), "https://k.example", none))["conversion"].severity == "high"
    only_text_phone = good_signals(tel_link_present=False, whatsapp_link_present=False, form_present=False, has_appointment_link=False, email_in_text=False, phone_in_text=True)
    c = by_key(build_website_checks(ctx(), "https://k.example", only_text_phone))["conversion"]
    assert c.severity == "low", "sayfada düz metin telefon varsa 'hiçbir iletişim noktası yok' denmemeli"


def test_ecommerce_check_only_for_product_selling_sectors():
    retail = ctx(sector="Giyim Mağazası", group="Perakende ve Mağazacılık", phrases=["giyim"])
    checks = by_key(build_website_checks(retail, "https://m.example", good_signals(has_shop_signals=False)))
    assert checks["ecommerce"].status == "problem" and checks["ecommerce"].services == (SVC_ECOM,)
    clinic = by_key(build_website_checks(ctx(), "https://m.example", good_signals(has_shop_signals=False)))
    assert "ecommerce" not in clinic


def test_booking_severity_depends_on_sector():
    s = good_signals(has_appointment_link=False, form_present=False)
    clinic = by_key(build_website_checks(ctx(), "https://m.example", s))["booking"]
    restaurant = by_key(build_website_checks(ctx("Restoran", "Yeme-İçme", phrases=["restoran"]), "https://m.example", s))["booking"]
    assert clinic.severity == "medium" and restaurant.severity == "low"


def test_social_link_finding_is_low_confidence_and_says_account_may_exist():
    c = by_key(build_website_checks(ctx(), "https://k.example", good_signals(social_links={})))["social_links"]
    assert c.status == "problem" and c.confidence == "low" and c.services == (SVC_SOCIAL,)
    assert "hiç olmadığı anlamına gelmez" in c.detail


def test_mentions_tolerates_turkish_suffixes():
    assert mentions("Sakarya'da restoranı", "restoran")
    assert mentions("ADAPAZARI", "Adapazarı")
    assert not mentions("barış", "bar"), "kısa anahtar kelime yalnızca tam kelime olarak eşleşmeli"


# ================================================================ GOOGLE İŞLETME PROFİLİ
def test_missing_google_profile_never_fabricates_google_data():
    checks = build_gbp_checks(ctx(source="google_maps"), listing_business(phone="0264 111 11 11"))
    assert len(checks) >= 10
    assert all(c.status == "unknown" for c in checks), "OSM kaynağında Google'a ait hiçbir alan sorun/ok olarak işaretlenmemeli"
    values = " ".join(c.value for c in checks)
    assert "Doğrulanamadı" in values
    rating = by_key(checks)["rating"]
    assert rating.value == "Doğrulanamadı"
    phone = by_key(checks)["phone"]
    assert "0264 111 11 11" in phone.value and phone.value.startswith("Doğrulanamadı"), "OSM'deki telefon 'Google'da doğrulanmadı' notuyla gösterilir"


def test_google_source_flags_real_gaps_with_why_and_service():
    biz = google_business(photo_count=2, google_review_count=4, google_rating=3.6, opening_hours=None, phone=None, website=None)
    checks = by_key(build_gbp_checks(ctx(source="google_places"), biz))
    for key in ("photos", "review_count", "rating", "hours", "phone", "website"):
        c = checks[key]
        assert c.status == "problem", key
        assert c.why, f"{key}: 'bu eksik neden önemli' yok"
        assert SVC_GBP in c.services
    assert SVC_CORPORATE_SITE in checks["website"].services, "Google profilinde web sitesi yoksa satılabilecek hizmet kurumsal web sitesidir"
    for key in ("photos", "review_count", "rating", "hours", "phone", "website"):
        c = checks[key]
        assert c.confidence == "high"
    assert checks["website"].severity == "high"
    assert checks["photos"].value == "Yalnızca 2 fotoğraf var"


def test_google_source_healthy_profile_is_ok():
    checks = build_gbp_checks(ctx(source="google_places"), google_business())
    assert [c.key for c in checks if c.status == "problem"] == []


def test_google_unavailable_fields_are_unknown_not_guessed():
    checks = by_key(build_gbp_checks(ctx(source="google_places"), google_business()))
    for key in ("description", "services_list", "last_photo", "review_replies"):
        assert checks[key].status == "unknown" and checks[key].value == "Doğrulanamadı"


def test_capped_photo_count_is_not_called_low():
    biz = google_business(photo_count=10, source_profile={"types": ["hearing_aid_store"], "primary_type": "hearing_aid_store", "photos_capped": True, "reviews_sampled": 5})
    c = by_key(build_gbp_checks(ctx(source="google_places"), biz))["photos"]
    assert c.status == "ok" and c.value == "10+ fotoğraf"


def test_missing_rating_or_reviews_are_unknown_not_zero():
    biz = google_business(google_review_count=None, google_rating=None, last_review_at=None, photo_count=None)
    checks = by_key(build_gbp_checks(ctx(source="google_places"), biz))
    for key in ("review_count", "rating", "last_review", "photos"):
        assert checks[key].status == "unknown", f"{key}: veri yokken 0 gibi yorumlanmamalı"


def test_review_count_compared_with_peers():
    biz = google_business(google_review_count=30)
    c = by_key(build_gbp_checks(ctx(source="google_places", peers=[200, 300, 250, 400]), biz))["review_count"]
    assert c.status == "problem" and "rakip" in c.value.lower()
    assert "ortanca" in c.detail


def test_stale_reviews_and_category_mismatch():
    biz = google_business(last_review_at=NOW - timedelta(days=400), category_label="Pizza restoranı",
                          source_profile={"types": ["restaurant"], "primary_type": "restaurant", "reviews_sampled": 5})
    checks = by_key(build_gbp_checks(ctx(source="google_places"), biz))
    assert checks["last_review"].status == "problem" and checks["last_review"].confidence == "low"
    assert checks["primary_category"].status == "problem" and "uyumsuz" in checks["primary_category"].value


def test_permanently_closed_business_is_flagged():
    biz = google_business(source_profile={"types": ["hearing_aid_store"], "primary_type": "hearing_aid_store", "business_status": "CLOSED_PERMANENTLY", "reviews_sampled": 5})
    checks = by_key(build_gbp_checks(ctx(source="google_places"), biz))
    assert checks["business_status"].status == "problem"


# ================================================================ SATIŞ DEĞERLENDİRMESİ
def run_assess(context, website, signals, gbp_business, *, phone=True):
    checks = build_website_checks(context, website, signals) + build_gbp_checks(context, gbp_business)
    return assess(context, checks, has_website=bool(website), contactable_phone=phone, contactable_email=False)


def test_no_website_and_no_google_profile_is_medium_needs_verification():
    a = run_assess(ctx(), None, None, listing_business(phone="0264 1"))
    assert a.level == "Orta" and a.needs_verification is True
    assert a.services[0].service == SVC_CORPORATE_SITE
    assert "Doğrulama gerekli" in a.level_reason
    assert any("Google'da" in step for step in a.verification_steps)
    assert any("Google Haritalar" in step for step in a.verification_steps), "OSM kaynağında Google profilini elle kontrol adımı olmalı"


def test_no_website_plus_bad_google_profile_is_high():
    biz = google_business(website=None, photo_count=0, google_review_count=2, google_rating=3.4)
    a = run_assess(ctx(source="google_places"), None, None, biz)
    assert a.level == "Yüksek" and a.needs_verification is False
    assert a.services[0].service == SVC_CORPORATE_SITE
    assert SVC_GBP in [s.service for s in a.services]
    assert a.top_opportunity.startswith(SVC_CORPORATE_SITE)
    assert "Web sitesi" in a.level_reason and "+" in a.level_reason


def test_strong_digital_presence_is_low_and_not_prioritized():
    a = run_assess(ctx(source="google_places"), "https://kaya.example", good_signals(), google_business())
    assert a.level == "Düşük"
    assert a.services == [] and a.top_opportunity is None and a.gaps == []
    assert a.rank_score < 2, "sırf işletme olduğu için ilk sıraya konmamalı"
    assert "somut bir eksik tespit edilmedi" in a.level_reason
    assert a.strengths, "güçlü yönler listelenmeli"


def test_many_minor_gaps_do_not_make_high():
    """Blog/hakkımızda/sitemap gibi düşük önemli eksikler toplanınca 'Yüksek' üretmemeli."""
    s = good_signals(has_blog=False, has_about_page=False, has_references_page=False, sitemap_present=False, schema_types=[], social_links={}, copyright_year=2020)
    a = run_assess(ctx(source="google_places"), "https://kaya.example", s, google_business())
    assert a.level in ("Düşük", "Orta")
    assert a.level != "Yüksek"


def test_inaccessible_site_and_no_other_data_is_uncertain_not_good():
    s = WebsiteSignals(success=False, outcome="blocked", error_reason="bot")
    a = run_assess(ctx(), "https://kaya.example", s, listing_business())
    assert a.level == "Belirsiz"
    assert a.rank_score == 0.0 and a.services == []
    assert "manuel" in a.level_reason.lower()


def test_hacked_site_is_high_with_urgent_wording():
    s = good_signals(title="Bokep Indonesia", spam_terms=["bokep", "porn"], text_excerpt="bokep", meta_description=None, h1_texts=[])
    a = run_assess(ctx(), "https://kaya.example", s, listing_business(phone="1"))
    assert a.level == "Yüksek" and a.needs_verification is False
    assert "ele geçirilmiş" in a.why_call and "acil" in a.sales_note.lower()


def test_services_are_evidence_based_only_and_unverified_ones_are_separate():
    s = good_signals(meta_description=None, h1_texts=[])
    a = run_assess(ctx(source="google_places"), "https://kaya.example", s, google_business())
    recommended = {x.service for x in a.services}
    assert recommended == {SVC_SEO}, "yalnızca gerçekten tespit edilen ihtiyaca bağlı hizmet önerilmeli"
    possible = {p["service"] for p in a.possible_services}
    assert not possible & recommended
    assert all(p["basis"] for p in a.possible_services)
    assert len(a.possible_services) <= 8, "bütün hizmetler otomatik yazılmamalı"
    assert len({p["service"] for p in a.possible_services}) == len(a.possible_services), "olası hizmetler tekrarsız olmalı"


def test_unknown_checks_never_contribute_to_level():
    ok_google = google_business()
    with_unknowns = run_assess(ctx(source="google_places"), "https://kaya.example",
                               good_signals(js_rendered_hint=True, word_count=10, h1_texts=[], h2_count=0, text_excerpt="", sitemap_present=None, copyright_year=None), ok_google)
    assert with_unknowns.level == "Düşük"
    assert with_unknowns.gaps == []


def test_closed_business_is_not_a_target():
    biz = google_business(source_profile={"types": ["x"], "primary_type": "x", "business_status": "CLOSED_PERMANENTLY", "reviews_sampled": 5}, website=None)
    a = run_assess(ctx(source="google_places"), None, None, biz)
    assert a.level == "Düşük" and "kapalı" in a.level_reason.lower()
    assert a.services == [] or a.top_opportunity is None


def test_sales_texts_present_and_use_real_context():
    s = good_signals(meta_description=None, h1_texts=[], title="Ana Sayfa")
    a = run_assess(ctx(source="google_places"), "https://kaya.example", s, google_business())
    assert a.level in ("Yüksek", "Orta")
    assert a.top_opportunity and a.why_call and a.talking_point and a.sales_note
    assert "Adapazarı" in a.talking_point and "işitme cihazı" in a.talking_point
    assert a.sales_note.startswith("Web siteniz")
    assert "Yerel SEO" in a.sales_note and "Kurumsal SEO" in a.sales_note


def test_ranking_prefers_contactable_businesses_at_same_need():
    a1 = run_assess(ctx(), None, None, listing_business(), phone=True)
    a2 = run_assess(ctx(), None, None, listing_business(), phone=False)
    assert a1.level == a2.level and a1.rank_score > a2.rank_score


def test_level_reason_starts_with_correct_turkish_capital():
    s = good_signals(tel_link_present=False, whatsapp_link_present=False, form_present=False, has_appointment_link=False, email_in_text=False, phone_in_text=False)
    a = run_assess(ctx(source="google_places"), "https://kaya.example", s, google_business())
    assert a.level_reason.startswith("İletişim/dönüşüm"), a.level_reason
