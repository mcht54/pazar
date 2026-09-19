"""Müşteri adayı uygunluğu: rakip / kamu kurumu / Mchttasarım'ın kendisi ayrımı (gerçek veri örnekleriyle)."""

import pytest

from services.rule_engine.prospect import KIND_COMPETITOR, KIND_INSTITUTION, KIND_PUBLIC, KIND_SELF, assess_prospect, business_categories

# (ad, kategoriler, sektör, beklenen tür)  — beklenen None = müşteri adayı KALMALI
CASES = [
    # --- Mchttasarım'ın kendisi
    ("MchTTasarıM Reklam Ajansı | Web Tasarım | Sosyal Medya | Matbaa", ["Web Sitesi Tasarımcısı"], "Web Tasarım ve Yazılım", KIND_SELF),
    # --- rakipler: kategoriye dayalı
    ("Sakarya Web Tasarım Ajansı", ["Web Sitesi Tasarımcısı"], "Web Tasarım ve Yazılım", KIND_COMPETITOR),
    ("TASEM Teknoloji", ["Yazılım Şirketi"], "Web Tasarım ve Yazılım", KIND_COMPETITOR),
    ("Digienseo", ["İnternet Pazarlamacılığı Hizmeti"], "Web Tasarım ve Yazılım", KIND_COMPETITOR),
    ("Bora Reklam ve Tabela", ["Reklam Ajansı"], "Tabelacı / Reklam Uygulama", KIND_COMPETITOR),
    ("Bir Matbaa", ["Matbaa"], "Matbaa ve Baskı", KIND_COMPETITOR),
    # rakip sektöründe, kategori yok, ad hizmeti açıkça söylüyor
    ("7 Proje Ofisi Görsel Tasarım Danışmanlık Ltd. Şti", [], "Reklam Ajansı", KIND_COMPETITOR),
    # --- kamu
    ("Adapazarı Bilim ve Sanat Merkezi Müdürlüğü", ["Eğitim Kurumu"], "Özel Okul", KIND_PUBLIC),
    ("Serdivan Belediyesi Fen İşleri", [], "Danışmanlık", KIND_PUBLIC),
    ("Sakarya Valiliği", ["Devlet Dairesi"], "Danışmanlık", KIND_PUBLIC),
    ("Atatürk Anadolu Lisesi", ["Lise"], "Özel Okul", KIND_PUBLIC),
    ("Şehit Mustafa Ozen İöo", ["Eğitim Kurumu"], "Özel Okul", KIND_PUBLIC),
    ("Adapazarı Özel Eğitim Uygulama Okulu 1. Kademe", ["Eğitim Kurumu"], "Özel Okul", KIND_PUBLIC),  # "Özel Eğitim" = özel okul DEĞİL
    ("Sakarya Eğitim ve Araştırma Hastanesi", ["Hastane"], "Özel Hastane", KIND_PUBLIC),
    # --- ticari olmayan kurumlar (ibadethane, dernek, sendika, oda, muhtarlık)
    ("Sakarya Merkez Camii", ["Cami"], "Danışmanlık", KIND_INSTITUTION),
    ("Adapazarı Esnaf ve Sanatkarlar Derneği", ["Dernek"], "Danışmanlık", KIND_INSTITUTION),
    ("Sakarya Ticaret Odası", [], "Danışmanlık", KIND_INSTITUTION),
    ("Hendek Muhtarlığı", [], "Danışmanlık", KIND_INSTITUTION),
    # --- GERÇEK MÜŞTERİLER: yanlışlıkla elenmemeli
    ("Camlı Cafe", ["Kafe"], "Kafe", None),  # "cam..." ile başlayan ad "cami" kurumu sayılmaz
    ("Kamil Cam ve Doğrama", ["Cam Ustası"], "Cam ve Doğrama", None),
    ("Özel Ölçün Anadolu Lisesi", ["Eğitim Kurumu"], "Özel Okul", None),
    ("Özel Anka Ortaokulu", ["İlköğretim Okulu"], "Özel Okul", None),
    ("Uğur Okulları Sakarya Kampüsü", ["Lise"], "Özel Okul", None),
    ("Enka Okulları", ["Eğitim"], "Özel Okul", None),
    ("Sakarya Bahçeşehir Koleji", ["Özel Okul"], "Özel Okul", None),
    ("Bahçeşehir Dil Okulu", ["Yabancı Dil Okulu"], "Yabancı Dil Okulu", None),
    ("IMA SAKARYA ÖZEL ÖĞRETİM KURUMU", ["Eğitim Kurumu"], "Özel Okul", None),
    ("Sakarya Üniversitesi Vakfı Özel Okulları", ["İlkokul"], "Özel Okul", None),
    ("Özer Kırtasiye", [], "Matbaa ve Baskı", None),  # rakip sektöründe bulundu ama matbaa/ajans değil
    ("Bilgi Kitabevi", [], "Matbaa ve Baskı", None),
    ("Kent Emlak Ajansı", ["Emlak Ajansı"], "Emlak Ofisi", None),  # çıplak "ajans" rakip sayılmaz
    ("Reklam Cafe", ["Kafe"], "Kafe", None),  # sektör rakip değil, kategori kafe → ad tek başına yetmez
    ("Teknik SES İŞİTME CİHAZLARI", ["İşitme Cihazları Satıcısı"], "İşitme Cihazı Merkezi", None),
    ("Özel Sakarya Tıp Merkezi", ["Özel Klinik"], "Özel Klinik / Poliklinik", None),
    ("Gazete Sakarya Haber", ["Gazete"], "Gazete ve Yayıncılık", None),
]


@pytest.mark.parametrize("name,categories,sector,expected", CASES, ids=[c[0][:40] for c in CASES])
def test_prospect_classification(name, categories, sector, expected):
    verdict = assess_prospect(name=name, categories=categories, sector_name=sector)
    assert verdict.kind == expected, f"{name}: {verdict.reason}"
    assert verdict.eligible == (expected is None)
    if expected:
        assert verdict.reason and verdict.label, "elenen her kayıt gerekçe göstermeli"


def test_own_company_is_detected_from_website_too():
    assert assess_prospect(name="Ajans X", categories=[], sector_name=None, website="https://www.mchttasarim.com").kind == KIND_SELF


def test_sector_alone_never_excludes():
    # rakip sektöründe ve kategori bilinmiyor, ad hizmeti söylemiyor → aday kalır
    assert assess_prospect(name="Yıldız Ticaret", categories=[], sector_name="Reklam Ajansı").eligible


def test_business_categories_merges_label_and_profile_and_drops_raw_osm_tags():
    cats = business_categories("Bilişim / Yazılım", {"categories": ["office=it", "Yazılım Şirketi", "Bilişim / Yazılım"]})
    assert cats == ["Bilişim / Yazılım", "Yazılım Şirketi"]
    assert assess_prospect(name="Desbil Destek Bilişim", categories=cats, sector_name="Web Tasarım ve Yazılım").kind == KIND_COMPETITOR
