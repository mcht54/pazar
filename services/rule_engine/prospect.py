"""Müşteri adayı uygunluğu: Mchttasarım'a GERÇEK satış fırsatı olmayan kayıtları (kendisi, rakipler, kamu kurumları) ayırt eder.

Yalnızca "Bugünün potansiyel müşterileri" panelinde kullanılır; puanı veya satış seviyesini değiştirmez.

İlke: yanlışlıkla gerçek müşteriyi elemek, bir rakibi listede bırakmaktan daha kötüdür. Bu yüzden hiçbir karar tek başına isme dayanmaz:
- Rakip: işletmenin Google kategorisi rakip hizmet türünü (web tasarım, reklam ajansı, matbaa…) söylüyorsa; ya da işletme rakip sektöründe
  bulunduysa VE kategorisi yoksa VE adı bu hizmeti açıkça söylüyorsa. Sektör tek başına yetmez ("Matbaa" aramasında çıkan kırtasiye kalır).
- Kamu: kategori kamu kurumu diyorsa; ya da ad kesin kurum ifadeleri içeriyorsa (Müdürlüğü, Belediyesi…); ya da ad + kategori birlikte
  "devlet okulu" gösteriyorsa (okul adı var, "Özel/Koleji/Okulları…" işareti yok, kategori okul türünde).
- Belirsizse aday KALIR.
"""

from dataclasses import dataclass

from packages.localization import contains_phrase, fold

KIND_SELF = "kendi"
KIND_COMPETITOR = "rakip"
KIND_PUBLIC = "kamu"
KIND_INSTITUTION = "kurum"

KIND_LABELS = {
    KIND_SELF: "Mchttasarım'ın kendisi",
    KIND_COMPETITOR: "Rakip firma (Mchttasarım'ın sunduğu hizmetleri veriyor)",
    KIND_PUBLIC: "Kamu kurumu / devlet okulu",
    KIND_INSTITUTION: "Kurum / dernek / ibadethane (ticari müşteri adayı değil)",
}
# ---- ticari olmayan kurumlar: ibadethane, dernek/sendika/oda, muhtarlık, siyasi parti (Google kategorisi)
_INSTITUTION_CATEGORY_TERMS = ("cami", "mescit", "kilise", "sinagog", "ibadet", "dernek", "sendika", "muhtarlik", "meslek odasi", "ticaret odasi", "sanayi odasi",
                               "siyasi parti", "sivil toplum", "vakif merkezi")
_INSTITUTION_NAME_PHRASES = ("camii", "cami", "muhtarligi", "dernegi", "sendikasi", "ticaret odasi", "sanayi odasi", "meslek odasi", "baro baskanligi", "tabip odasi")

# ---- rakip: Google kategorisi (katlanmış metinde alt dize). Çıplak "ajans" bilerek YOK ("Emlak Ajansı" rakip değildir.)
_COMPETITOR_CATEGORY_TERMS = (
    "web sitesi tasarim", "web tasarim", "reklam", "tasarim ajans", "dijital ajans", "dijital pazarlama", "internet pazarlamaciligi",
    "pazarlama ajans", "medya ajans", "sosyal medya", "yazilim", "bilisim", "grafik tasarim", "matbaa", "dijital baski", "ofset",
    "tabela", "promosyon",
)
# ---- rakip sektörleri (Mchttasarım'ın hizmet alanları) — tek başına yetmez, kategori/ad ile birlikte değerlendirilir
_COMPETITOR_SECTORS = {
    fold(s) for s in ("Web Tasarım ve Yazılım", "Reklam Ajansı", "Tabelacı / Reklam Uygulama", "Matbaa ve Baskı", "Promosyon Ürünleri Tedarikçisi")
}
_COMPETITOR_NAME_TERMS = (
    "reklam", "ajans", "web", "tasarim", "dijital", "matbaa", "tabela", "baski", "yazilim", "bilisim", "promosyon", "ofset", "medya", "grafik",
)

# ---- kamu
_PUBLIC_CATEGORY_TERMS = (
    "devlet dairesi", "devlet kurumu", "kamu kurumu", "kamu hizmet", "belediye", "valilik", "kaymakamlik", "hukumet", "vergi dairesi",
    "emniyet", "polis", "itfaiye", "adliye", "mahkeme", "nufus", "tapu ve kadastro", "devlet okulu", "devlet lisesi", "kamu okulu", "resmi kurum",
    "yerel yonetim", "devlet hastanesi", "kamu hastanesi",
)
_PUBLIC_NAME_PHRASES = (
    "mudurlugu", "belediyesi", "belediye baskanligi", "valiligi", "kaymakamligi", "adliyesi", "vergi dairesi", "milli egitim",
    "halk egitim merkezi", "rehberlik ve arastirma merkezi", "bilim ve sanat merkezi", "devlet hastanesi", "egitim ve arastirma hastanesi",
    "sehir hastanesi", "aile sagligi merkezi", "toplum sagligi merkezi", "rektorlugu", "genel mudurlugu", "bolge mudurlugu",
)
# "anaokulu/kreş" bilerek YOK: özel anaokulları çoğunlukla "Özel" yazmadan da adlandırılır → adıyla devlet/özel ayrımı güvenilir değil, aday KALIR
_SCHOOL_NAME_TOKENS = ("lisesi", "ortaokulu", "ilkokulu", "ioo", "okulu")
_SCHOOL_CATEGORY_TERMS = ("lise", "ilkokul", "ortaokul", "ilkogretim", "egitim kurumu", "genel egitim", "okul", "egitim merkezi")
# özel (ticari) okul/kurs işaretleri — adında ya da kategorisinde varsa kamu okulu sayılmaz. Kelime tabanlı eşleşir (alt dize değil).
_PRIVATE_EDU_PREFIXES = ("ozel", "kolej", "okullari", "kampus", "vakif", "vakfi", "kurs", "dershane", "etut", "akademi", "kres", "anaokullari", "ogretim")
_PRIVATE_EDU_PHRASES = ("egitim kurumlari", "dil okulu", "a s")


@dataclass(frozen=True)
class ProspectVerdict:
    eligible: bool
    kind: str | None = None
    reason: str | None = None  # kullanıcıya gösterilen kısa gerekçe

    @property
    def label(self) -> str | None:
        return KIND_LABELS.get(self.kind) if self.kind else None


_OK = ProspectVerdict(True)


def _has_term(text: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        if term in text:
            return term
    return None


def _has_private_edu_marker(text_folded: str) -> bool:
    tokens = text_folded.split()
    padded = f" {text_folded} "
    return (
        any(t.startswith(p) for t in tokens for p in _PRIVATE_EDU_PREFIXES)
        or any(t in ("ltd", "sti") for t in tokens)
        or any(f" {p} " in padded for p in _PRIVATE_EDU_PHRASES)
    )


def _name_has_word(name_folded: str, words: tuple[str, ...]) -> str | None:
    padded = f" {name_folded} "
    for word in words:
        if f" {word} " in padded or any(token.startswith(word) for token in name_folded.split()):
            return word
    return None


def assess_prospect(*, name: str, categories: list[str] | None, sector_name: str | None, website: str | None = None) -> ProspectVerdict:
    name_f = fold(name or "")
    cats = [fold(c) for c in (categories or []) if c]
    cat_text = " | ".join(cats)
    sector_f = fold(sector_name or "")
    cat_display = ", ".join(c for c in (categories or []) if c)

    # 1) Mchttasarım'ın kendisi
    if "mchttasarim" in name_f.replace(" ", "") or "mchttasarim" in fold(website or "").replace(" ", ""):
        return ProspectVerdict(False, KIND_SELF, "Adında/web adresinde Mchttasarım geçiyor.")

    # 2) kamu kurumu
    term = _has_term(cat_text, _PUBLIC_CATEGORY_TERMS)
    if term and "ozel" not in cat_text:
        return ProspectVerdict(False, KIND_PUBLIC, f"Google kategorisi kamu kurumunu gösteriyor ({cat_display}).")
    if name_f.startswith("t c "):
        return ProspectVerdict(False, KIND_PUBLIC, "Adı 'T.C.' ile başlıyor.")
    for phrase in _PUBLIC_NAME_PHRASES:
        if contains_phrase(name_f, phrase):
            return ProspectVerdict(False, KIND_PUBLIC, f"Adında kamu kurumu ifadesi var ('{phrase}').")
    # devlet okulu çıkarımı: okul adı + okul türünde kategori + hiçbir özel/ticari işaret yok ("Özel Eğitim" ibaresi özel okul sayılmaz)
    school_word = _name_has_word(name_f, _SCHOOL_NAME_TOKENS)
    if school_word and (not cats or _has_term(cat_text, _SCHOOL_CATEGORY_TERMS)):
        check_name = name_f.replace("ozel egitim", " ")
        if not _has_private_edu_marker(check_name) and not _has_private_edu_marker(cat_text):
            return ProspectVerdict(False, KIND_PUBLIC, f"Devlet okulu olarak değerlendirildi: adında '{school_word}' var, 'Özel/Koleji/Okulları' gibi özel okul işareti yok.")

    # 2b) ticari olmayan kurum (ibadethane, dernek, sendika, oda, muhtarlık)
    term = _has_term(cat_text, _INSTITUTION_CATEGORY_TERMS)
    if term:
        return ProspectVerdict(False, KIND_INSTITUTION, f"Google kategorisi ticari olmayan kurumu gösteriyor ({cat_display}).")
    for phrase in _INSTITUTION_NAME_PHRASES:
        if contains_phrase(name_f, phrase):
            return ProspectVerdict(False, KIND_INSTITUTION, f"Adında ticari olmayan kurum ifadesi var ('{phrase}').")

    # 3) rakip
    term = _has_term(cat_text, _COMPETITOR_CATEGORY_TERMS)
    if term:
        return ProspectVerdict(False, KIND_COMPETITOR, f"Google kategorisi rakip hizmet türünü gösteriyor ({cat_display}).")
    if sector_f in _COMPETITOR_SECTORS and not cats:
        word = _name_has_word(name_f, _COMPETITOR_NAME_TERMS)
        if word:
            return ProspectVerdict(False, KIND_COMPETITOR, f"Rakip sektöründe ({sector_name}) bulundu, Google kategorisi yok ve adı '{word}' hizmetini gösteriyor.")

    return _OK


def business_categories(category_label: str | None, source_profile: dict | None) -> list[str]:
    """İşletmenin bilinen tüm Google kategorileri: okunabilir etiket + kaynak profildeki kategoriler.

    Eski (OpenStreetMap dönemi) kayıtlardaki ham etiketler ('office=it') kategori sayılmaz.
    """
    found: list[str] = []
    for value in [category_label, *((source_profile or {}).get("categories") or [])]:
        if isinstance(value, str) and value.strip() and "=" not in value and value not in found:
            found.append(value.strip())
    return found


def assess_business(business, sector_name: str | None) -> ProspectVerdict:
    """`Business` kaydı için assess_prospect (kategori + sektör + ad + web adresi birlikte)."""
    return assess_prospect(
        name=business.name,
        categories=business_categories(business.category_label, business.source_profile),
        sector_name=sector_name,
        website=business.website,
    )
