"""Bing Haritalar (Microsoft) işletme kartı — Google'dan BAĞIMSIZ ikinci dizin kaynağı.

Aranan işletme için Bing'in gösterdiği tek "işletme kartı" okunur: ad, web sitesi, adres, telefon, çalışma saati, konum.
Google ile aynı bilgiyi verirse çapraz doğrulama güçlenir; farklıysa çelişki olarak işaretlenir.
Kart, konum + ad (+ telefon/adres) ile eşleşmiyorsa kullanılmaz. Engel görülürse aşılmaz (bkz. browser.py).
"""

import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from services.research.browser import browser_page, guarded_goto, source_lock
from services.research.matching import score_match
from services.research.models import BusinessQuery, DirectoryProfile

SOURCE = "bing_maps"

_CARD_JS = """() => {
  const c = document.querySelector('.b_lcmgzentitycard'); if (!c) return null;
  return {
    text: c.innerText,
    title: c.querySelector('.eh_title') ? c.querySelector('.eh_title').innerText : null,
    desc: c.querySelector('.ed_entity_desc') ? c.querySelector('.ed_entity_desc').innerText : null,
    links: [...c.querySelectorAll('a[href]')].map(a => ({t: (a.innerText || '').trim().slice(0, 60), h: a.href}))
  };
}"""


def parse_card(payload: dict) -> DirectoryProfile:
    """Bing işletme kartı çıktısını DirectoryProfile'a çevirir. Bulunamayan alan None kalır."""
    lines = [ln.strip() for ln in (payload.get("text") or "").split("\n") if ln.strip()]
    profile = DirectoryProfile(source=SOURCE, name=(payload.get("title") or (lines[0] if lines else None)) or None)
    profile.description = (payload.get("desc") or "").strip() or None

    category_index = next((i for i, ln in enumerate(lines) if "konumunda" in ln), None)
    if category_index is not None:
        profile.category = re.sub(r"^.*konumunda\s*", "", lines[category_index]).strip() or None
        if category_index + 1 < len(lines):
            candidate = lines[category_index + 1]
            if re.search(r"\d", candidate) or re.search(r"(?i)cadde|sokak|mah|bulvar", candidate):
                profile.address = candidate
    # Not: Bing kartındaki "Kapalı · Yarın 09:00 itibarıyla açılacak" bir DURUM satırıdır, çalışma saati tablosu değildir;
    # çapraz doğrulamada saat olarak kullanılmaz.

    for link in payload.get("links") or []:
        href = link.get("h") or ""
        if href.startswith("tel:") and not profile.phone:
            profile.phone = link.get("t") or href[4:]
        elif "/alink/link" in href and not profile.website:
            target = parse_qs(urlparse(href).query).get("url", [None])[0]
            if target and target.startswith("http"):
                profile.website = unquote(target)
        elif "directions?rtp=" in href and profile.lat is None:
            pos = re.search(r"pos\.(-?\d+\.\d+)_(-?\d+\.\d+)", href)
            if pos:
                profile.lat, profile.lng = float(pos.group(1)), float(pos.group(2))
    return profile


def lookup(query: BusinessQuery) -> tuple[DirectoryProfile | None, str]:
    """Döndürür: (eşleşen profil | None, açıklama). SourceBlocked/SourceError çağırana yükselir."""
    text = f"{query.name} {query.place}".strip()
    center = f"&cp={query.lat}~{query.lng}" if query.lat is not None and query.lng is not None else ""
    with source_lock(SOURCE), browser_page() as page:
        guarded_goto(page, f"https://www.bing.com/maps?q={quote(text)}{center}&lvl=16", SOURCE, wait_ms=4500, min_interval=3.0)
        payload = page.evaluate(_CARD_JS)
    if not payload:
        return None, "Bing Haritalar bu arama için bir işletme kartı göstermedi."
    profile = parse_card(payload)
    profile.url = f"https://www.bing.com/maps?q={quote(text)}"
    profile.match = score_match(query, name=profile.name, lat=profile.lat, lng=profile.lng, phone=profile.phone, address=profile.address)
    if not profile.match.accepted:
        return None, f"Bing Haritalar'daki kart ('{profile.name}') bu işletmeyle güvenle eşleşmedi ({'; '.join(profile.match.negatives + profile.match.signals)})."
    return profile, f"Bing Haritalar'da eşleşen kart bulundu ({', '.join(profile.match.signals)})."
