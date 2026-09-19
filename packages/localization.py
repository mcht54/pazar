"""Türkçe yerelleştirme yardımcıları: Türkçe karakter-duyarlı metin karşılaştırma ve alan adı normalizasyonu."""

import re
import unicodedata

_TR_UPPER_TO_LOWER = str.maketrans({"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"})


def tr_lower(text: str) -> str:
    """Türkçe kurallı küçük harfe çevirme (İ→i, I→ı)."""
    return (text or "").translate(_TR_UPPER_TO_LOWER).lower()


def tr_capitalize_first(text: str) -> str:
    """İlk harfi Türkçe kurallı büyütür (i→İ, ı→I); Python'un upper()'ı 'i'yi 'I' yapar."""
    if not text:
        return text
    first = {"i": "İ", "ı": "I"}.get(text[0], text[0].upper())
    return first + text[1:]


def fold(text: str) -> str:
    """Karşılaştırma için normalleştirme: Türkçe küçük harf + aksan/nokta kaldırma + tek boşluk.

    'Adapazarı', 'ADAPAZARI' ve 'adapazari' aynı sonucu verir.
    """
    lowered = tr_lower(text).replace("ı", "i")
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def contains_phrase(haystack: str, needle: str) -> bool:
    """Katlanmış metinde ifade (kelime sınırlarıyla) geçiyor mu?"""
    n = fold(needle)
    if not n:
        return False
    return f" {n} " in f" {fold(haystack)} "


def normalize_host(url: str | None) -> str | None:
    """Web adresinin karşılaştırılabilir alan adı (www./şema/yol olmadan). Aynı sitenin farklı yazımlarını tek yapar."""
    if not url:
        return None
    value = url.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    host = re.split(r"[/?#;\s,]", value)[0].removeprefix("www.")
    return host or None
