"""Araştırma katmanı için normalizasyon yardımcıları: telefon, adres, ad, alan adı, puan/yorum, göreli tarih.

Hepsi saf fonksiyondur (ağ yok) ve birim testleriyle doğrulanır. Amaç: farklı kaynaklardan gelen aynı bilginin
("(0264) 277 45 05", "+90 264 2774505") aynı bilgi olarak tanınması ve YANLIŞ eşleşmenin önlenmesi.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from packages.localization import fold, normalize_host

# ----------------------------------------------------------------------------- telefon
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\+?\s?90[\s.-]?|0\s?)?\(?\s?[2-5]\d{2}\s?\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)")


def normalize_phone(raw: str | None) -> str | None:
    """Türkiye numarasını 10 haneli ulusal biçime çevirir ('2642774505'); geçerli değilse None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0090"):
        digits = digits[4:]
    elif digits.startswith("90") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "2345":
        return digits
    return None


def format_phone(normalized: str | None) -> str | None:
    if not normalized or len(normalized) != 10:
        return None
    return f"0{normalized[:3]} {normalized[3:6]} {normalized[6:8]} {normalized[8:]}"


def extract_phones(text: str | None) -> list[str]:
    """Metindeki geçerli telefon numaralarını (normalize, tekil, görülme sırasıyla) döndürür."""
    found: list[str] = []
    for match in _PHONE_CANDIDATE_RE.finditer(text or ""):
        number = normalize_phone(match.group(0))
        if number and number not in found:
            found.append(number)
    return found


def phones_equal(a: str | None, b: str | None) -> bool:
    na, nb = normalize_phone(a), normalize_phone(b)
    return bool(na and nb and na == nb)


# ----------------------------------------------------------------------------- puan / yorum / tarih
def parse_rating(text: str | None) -> float | None:
    """'5,0' / '4.7' -> float (0-5 aralığı dışı reddedilir)."""
    if not text:
        return None
    match = re.search(r"\d(?:[.,]\d)?", text)
    if not match:
        return None
    value = float(match.group(0).replace(",", "."))
    return value if 0 <= value <= 5 else None


def parse_count(text: str | None) -> int | None:
    """'(110)' / '110 yorum' / '1,2 B' (bin) / '1.234' -> int."""
    if not text:
        return None
    cleaned = text.strip().lower()
    thousand = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:b|bin)\b", cleaned)
    if thousand:
        return int(round(float(thousand.group(1).replace(",", ".")) * 1000))
    match = re.search(r"\d[\d.]*", cleaned)
    if not match:
        return None
    return int(match.group(0).replace(".", ""))


_UNIT_DAYS = {"dakika": 0, "saat": 0, "gün": 1, "hafta": 7, "ay": 30, "yıl": 365}
_REL_RE = re.compile(r"(?:(\d+)|bir|geçen)\s*(dakika|saat|gün|hafta|ay|yıl)\s*önce", re.IGNORECASE)


def relative_time_to_date(text: str | None, now: datetime | None = None) -> datetime | None:
    """Google'ın göreli tarihini ('5 ay önce', 'bir hafta önce') YAKLAŞIK tarihe çevirir.

    Sonuç kesin değildir (Google günü vermez); ekranda 'yaklaşık' diye etiketlenmelidir.
    """
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    lowered = text.lower()
    if "az önce" in lowered:
        return now
    match = _REL_RE.search(lowered)
    if not match:
        return None
    amount = int(match.group(1)) if match.group(1) else 1
    unit = match.group(2)
    if unit in ("dakika", "saat"):
        return now
    return now - timedelta(days=amount * _UNIT_DAYS[unit])


# ----------------------------------------------------------------------------- konum / alan adı
def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def coords_from_maps_url(url: str | None) -> tuple[float, float] | None:
    """Google Maps yer adresinden YERİN koordinatı: yalnızca !3d..!4d (yerin kendisi).

    '@lat,lng' ifadesi HARİTA GÖRÜNÜMÜNÜN merkezidir (aramaya biz verdiğimiz konum olabilir) — asla yerin konumu sayılmaz.
    """
    if not url:
        return None
    exact = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    return (float(exact.group(1)), float(exact.group(2))) if exact else None


def same_site(a: str | None, b: str | None) -> bool:
    ha, hb = normalize_host(a), normalize_host(b)
    return bool(ha and hb and ha == hb)


def registrable_label(url: str | None) -> str | None:
    """'https://www.siser.com.tr/x' -> 'siser' (marka kısmı; alan adı-ad benzerliği için)."""
    host = normalize_host(url)
    if not host:
        return None
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu", "web", "biz"):
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


# ----------------------------------------------------------------------------- ad benzerliği
# Sektörü/şubeyi/hukuki türü anlatan sözcükler markayı ayırt etmez: "X İşitme Cihazları" ile "Y İşitme Cihazları"
# aynı sözcüklerle örtüşür ama farklı işletmelerdir. Bu yüzden benzerlik MARKA sözcükleri üzerinden ölçülür.
GENERIC_NAME_TOKENS = {
    "isitme", "cihazi", "cihazlari", "merkezi", "merkez", "sube", "subesi", "ltd", "sti", "limited", "sirketi", "anonim", "as",
    "san", "tic", "ve", "ile", "dis", "klinigi", "klinik", "poliklinigi", "eczanesi", "eczane", "restoran", "restaurant",
    "lokantasi", "lokanta", "otel", "hotel", "kafe", "cafe", "market", "kuafor", "berber", "guzellik", "salonu", "optik",
    "gozlukcu", "saticisi", "satis", "uygulama", "hizmetleri", "ticaret", "sanayi", "insaat", "mimarlik", "hukuk", "burosu",
    "muhasebe", "sigorta", "acentesi", "emlak", "oto", "servis", "galeri", "the", "of", "and",
}


def name_tokens(name: str | None) -> list[str]:
    return [t for t in fold(name or "").split() if t]


def brand_tokens(name: str | None, extra_generic: set[str] | None = None) -> list[str]:
    generic = GENERIC_NAME_TOKENS | (extra_generic or set())
    return [t for t in name_tokens(name) if t not in generic and len(t) > 1]


def name_similarity(a: str | None, b: str | None, extra_generic: set[str] | None = None) -> float:
    """0-1. Marka sözcükleri ortaksa yüksek; ikisinin de markası var ama hiç ortak değilse düşük (yanlış eşleşme koruması)."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    ba, bb = brand_tokens(a, extra_generic), brand_tokens(b, extra_generic)

    def contains_loose(tokens_a: list[str], tokens_b: list[str]) -> float:
        """Küçük kümenin ne kadarı büyükte (ek/yazım farkı toleranslı) geçiyor."""
        small, large = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
        hits = sum(1 for t in small if any(t == u or (len(t) >= 4 and (u.startswith(t) or t.startswith(u))) for u in large))
        return hits / len(small)

    if ba and bb:
        # tire ile yazılan markalar ("si-ser" -> si, ser) tek sözcük olarak da kıyaslanır
        joined_a, joined_b = "".join(ba), "".join(bb)
        if joined_a == joined_b or joined_a in joined_b or joined_b in joined_a:
            return 1.0
        return round(contains_loose(ba, bb), 2)
    # en az birinin markası yok (yalnızca genel sözcükler): genel örtüşme, ama en fazla 0.6 (kanıt zayıf)
    return round(min(0.6, contains_loose(ta, tb)), 2)


# ----------------------------------------------------------------------------- adres benzerliği
_ADDRESS_ABBREVIATIONS = {
    "cd": "cadde", "cad": "cadde", "caddesi": "cadde", "sk": "sokak", "sok": "sokak", "sokagi": "sokak", "mah": "mahalle",
    "mahallesi": "mahalle", "blv": "bulvar", "bulvari": "bulvar",
}
_ADDRESS_NOISE = {"no", "d", "kat", "apt", "daire", "turkiye", "turkey", "is", "merkezi", "blok", "ic", "kapi"}


def address_tokens(address: str | None, exclude: set[str] | None = None) -> set[str]:
    tokens: set[str] = set()
    skip = exclude or set()
    for token in fold(address or "").split():
        token = _ADDRESS_ABBREVIATIONS.get(token, token)
        if token in _ADDRESS_NOISE or token in skip or len(token) < 2:
            continue
        tokens.add(token)
    return tokens


def address_overlap(a: str | None, b: str | None, exclude: set[str] | None = None) -> float | None:
    """İki adresin ortak anlamlı sözcük oranı (küçük kümeye göre). Birinde anlamlı sözcük yoksa None (karşılaştırılamaz)."""
    ta, tb = address_tokens(a, exclude), address_tokens(b, exclude)
    if len(ta) < 2 or len(tb) < 2:
        return None
    return round(len(ta & tb) / min(len(ta), len(tb)), 2)
