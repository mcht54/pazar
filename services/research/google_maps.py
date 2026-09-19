"""Google Haritalar'dan (resmi API OLMADAN) işletme profili okuma.

Gerçek bir Chromium ile herkese açık Haritalar sayfası bir kullanıcı gibi açılır (tr-TR, oturumsuz "sınırlı görünüm").
Okunanlar: ad, puan, yorum sayısı, kategori, adres, telefon, web sitesi, çalışma saatleri, Haritalar bağlantısı,
"Hakkında" sekmesindeki özellikler/açıklama, en yeni yorumların (göreli) tarihi ve işletme yanıtı, kapak fotoğrafı tarihi.

Dürüstlük:
- Sonuç, aranan işletmeyle KONUM + AD (+ telefon/adres) ile eşleştirilir; eşleşmiyorsa hiçbir veri alınmaz.
- Google tarihleri göreli verir ("5 ay önce"): son yorum tarihi YAKLAŞIK etiketlidir.
- Okunamayan her alan None kalır. CAPTCHA/consent görülürse durulur (bkz. browser.py); aşılmaz.
- Bu, Google'ın kullanım şartlarının otomatik erişime izin vermediği bir yöntemdir; düşük hacim + önbellek + hız sınırıyla
  ve yalnızca kullanıcının talebiyle çalışır.
"""

import re
from datetime import datetime, timezone
from urllib.parse import quote

from services.research.browser import SourceBlocked, SourceError, browser_page, guarded_goto, source_lock
from services.research.matching import score_match
from services.research.models import BusinessQuery, DirectoryProfile, MapsCandidate
from services.research.normalize import (
    coords_from_maps_url,
    parse_count,
    parse_rating,
    relative_time_to_date,
)

SOURCE = "google_maps"
MAX_CANDIDATES = 6
MAX_REVIEWS = 10

_DAY_ORDER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
_DAY_SHORT = {"Pazartesi": "Pzt", "Salı": "Sal", "Çarşamba": "Çar", "Perşembe": "Per", "Cuma": "Cum", "Cumartesi": "Cmt", "Pazar": "Paz"}

_PLACE_JS = """() => {
  const q = s => document.querySelector(s);
  const items = [...document.querySelectorAll('[data-item-id]')].map(e => ({
    id: e.getAttribute('data-item-id'), aria: e.getAttribute('aria-label'), href: e.getAttribute('href'), txt: (e.innerText || '').trim()}));
  return {
    name: (q('h1') && q('h1').innerText || '').trim(),
    ratingBlock: q('div.F7nice') ? q('div.F7nice').innerText : null,
    imgAria: [...document.querySelectorAll('[role="img"][aria-label]')].map(e => e.getAttribute('aria-label')),
    category: q('button.DkEaL') ? q('button.DkEaL').innerText : null,
    items: items,
    hoursAria: [...document.querySelectorAll('[aria-label*="Çalışma saatlerini kopyala"]')].map(e => e.getAttribute('aria-label')),
    tabs: [...document.querySelectorAll('button[role="tab"]')].map(e => e.innerText.trim()),
    url: location.href
  };
}"""

_FEED_JS = """() => [...document.querySelectorAll('div[role="feed"] > div')].map(d => {
  const a = d.querySelector('a.hfpxzc'); if (!a) return null;
  return {name: a.getAttribute('aria-label'), href: a.getAttribute('href'), text: d.innerText.replace(/\\n+/g, ' | ')};
}).filter(Boolean)"""

_REVIEWS_JS = """() => {
  const seen = new Set(); const out = [];
  for (const el of document.querySelectorAll('div[data-review-id]')) {
    const id = el.getAttribute('data-review-id');
    if (seen.has(id)) continue; seen.add(id);
    out.push({id: id, text: el.innerText.replace(/\\n+/g, ' | ')});
  }
  return out;
}"""


# ----------------------------------------------------------------------------- saf ayrıştırıcılar (birim testli)
def parse_place_payload(payload: dict) -> DirectoryProfile:
    """_PLACE_JS çıktısını DirectoryProfile'a çevirir. Bulunamayan alan None kalır."""
    profile = DirectoryProfile(source=SOURCE, name=payload.get("name") or None, url=payload.get("url"))
    profile.category = (payload.get("category") or "").strip() or None

    # puan + yorum sayısı: "5,0\n(110)" ya da aria etiketleri ("5,0 yıldızlı", "110 yorum")
    block = payload.get("ratingBlock") or ""
    parts = [p.strip() for p in block.split("\n") if p.strip()]
    if parts:
        profile.rating = parse_rating(parts[0])
        if len(parts) > 1:
            profile.review_count = parse_count(parts[1])
    for aria in payload.get("imgAria") or []:
        if profile.rating is None and re.match(r"^\d[.,]\d\s*yıldız", aria):
            profile.rating = parse_rating(aria)
        if profile.review_count is None and re.match(r"^[\d.]+\s*yorum$", aria.strip()):
            profile.review_count = parse_count(aria)

    for item in payload.get("items") or []:
        item_id, aria, href, text = item.get("id") or "", item.get("aria") or "", item.get("href"), item.get("txt") or ""
        if item_id == "address":
            profile.address = re.sub(r"^Adres:\s*", "", aria).strip() or text or None
        elif item_id == "authority":
            profile.website = href or None
        elif item_id.startswith("phone:tel:"):
            profile.phone = re.sub(r"^Telefon:\s*", "", aria).strip() or text or None
        elif item_id == "oloc":
            profile.plus_code = re.sub(r"^Plus code:\s*", "", aria).strip() or None
        elif item_id.startswith("action:") and href and href.startswith("http") and "google." not in href.split("/")[2]:
            profile.extra_links.append(href)  # ör. şube sayfası / randevu / menü bağlantısı

    # çalışma saatleri: "Cuma,09:00 - 18:30, Çalışma saatlerini kopyala"
    by_day: dict[str, str] = {}
    for aria in payload.get("hoursAria") or []:
        match = re.match(r"^([^,]+),(.+?),\s*Çalışma saatlerini kopyala", aria)
        if match and match.group(1) in _DAY_ORDER:
            by_day.setdefault(match.group(1), match.group(2).strip())
    profile.hours = [{"day": day, "hours": by_day[day]} for day in _DAY_ORDER if day in by_day]
    if profile.hours:
        profile.hours_text = "; ".join(
            f"{_DAY_SHORT[h['day']]} {'kapalı' if h['hours'].lower() == 'kapalı' else h['hours'].replace(' - ', '-')}" for h in profile.hours
        )

    match = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", payload.get("url") or "")
    profile.place_id = match.group(1) if match else None
    coords = coords_from_maps_url(payload.get("url"))  # yalnızca !3d!4d — arama merkezi (@) yerin konumu sayılmaz
    if coords:
        profile.lat, profile.lng = coords
    return profile


def parse_feed_card(card: dict) -> MapsCandidate:
    """Sonuç listesindeki kart: 'Ad | Ad | 5,0(65) | Kategori · Adres | Kapalı ⋅ ... · 0537 700 31 46 | ...'"""
    text = card.get("text") or ""
    candidate = MapsCandidate(name=card.get("name") or "", url=card.get("href") or "", text=text)
    coords = coords_from_maps_url(candidate.url)
    if coords:
        candidate.lat, candidate.lng = coords
    rating = re.search(r"(\d[.,]\d)\s*\((\d[\d.]*)\)", text)
    if rating:
        candidate.rating, candidate.review_count = parse_rating(rating.group(1)), parse_count(rating.group(2))
    segments = [s.strip() for s in text.split("|") if s.strip()]
    for segment in segments:
        if "·" in segment and not re.search(r"Açılış|Kapan|Açık|saat", segment):
            pieces = [p.strip() for p in segment.split("·") if p.strip()]
            if pieces:
                candidate.category = pieces[0]
                if len(pieces) > 1:
                    candidate.address = pieces[-1]
            break
    phone = re.search(r"(?:\(0\d{3}\)\s?\d{3}[\s]?\d{2}[\s]?\d{2}|0\d{3}\s?\d{3}\s?\d{2}\s?\d{2}|\+90[\d\s]{10,14})", text)
    candidate.phone = phone.group(0).strip() if phone else None
    return candidate


def parse_reviews(raw_reviews: list[dict], now: datetime | None = None) -> tuple[list[dict], datetime | None, str | None, int]:
    """Yorum listesinden (göreli tarih, işletme yanıtı) çıkarır. Döndürür: (yorumlar, en yeni tarih, göreli metin, yanıt sayısı)."""
    now = now or datetime.now(timezone.utc)
    reviews: list[dict] = []
    for raw in raw_reviews[:MAX_REVIEWS]:
        text = raw.get("text") or ""
        relative = re.search(r"((?:\d+|bir)\s*(?:dakika|saat|gün|hafta|ay|yıl)\s*önce|az önce)", text)
        when = relative.group(1) if relative else None
        reviews.append({"relative": when, "approx_date": (relative_time_to_date(when, now).isoformat() if when and relative_time_to_date(when, now) else None),
                        "has_owner_reply": "İşletme sahibinin yanıtı" in text})
    dated = [(relative_time_to_date(r["relative"], now), r["relative"]) for r in reviews if r["relative"]]
    dated = [d for d in dated if d[0] is not None]
    newest = max(dated, key=lambda d: d[0]) if dated else (None, None)
    return reviews, newest[0], newest[1], sum(1 for r in reviews if r["has_owner_reply"])


_ICON_GLYPH_RE = re.compile(r"^[\ue000-\uf8ff]+\s*")


def parse_about_text(text: str | None) -> tuple[list[str], str | None]:
    """'Hakkında' sekmesi metninden (özellikler, açıklama).

    Özellikler onay simgesiyle (özel karakter) işaretlenir; simge ya satır başında ya da AYRI bir satırda gelir
    (metin bir sonraki satırdadır). Başlıklar ("Hizmet seçenekleri") atlanır. Açıklama: simgesiz, uzun
    (>= 60 karakter) serbest metindir. Bulunamayan alan boş/None kalır.
    """
    attributes: list[str] = []
    description = None
    lines = [ln.strip().replace("\xa0", "").strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in ("Hakkında", "Genel Bakış", "Yorumlar"):
            i += 1
            continue
        if _ICON_GLYPH_RE.match(line):
            item = _ICON_GLYPH_RE.sub("", line).strip()
            if not item and i + 1 < len(lines):  # simge ayrı satırda: metin sonraki satırdadır
                i += 1
                item = lines[i].strip()
            if item:
                attributes.append(item)
        elif len(line) >= 60 and description is None:
            description = line
        i += 1
    return attributes, description


# ----------------------------------------------------------------------------- tarayıcı akışı
def _wait_view(page) -> str:
    """Yüklenen görünüm türü: 'feed' (sonuç listesi) | 'place' (tek yer) | 'none'."""
    for _ in range(30):
        if page.locator('div[role="feed"] a.hfpxzc').count():
            return "feed"
        if page.locator("h1").count() and (page.locator('[data-item-id="address"]').count() or page.locator("div.F7nice").count()):
            return "place"
        page.wait_for_timeout(500)
    return "place" if page.locator("h1").count() and page.locator('button[role="tab"]').count() else "none"


def _settle_place_url(page) -> None:
    """Yer sayfası açıldıktan sonra URL'nin yerin gerçek koordinatını (!3d..!4d) içermesini bekler (en fazla ~8 sn)."""
    for _ in range(16):
        if "/maps/place/" in page.url and "!3d" in page.url:
            return
        page.wait_for_timeout(500)


def _search_url(query: str, lat: float | None, lng: float | None) -> str:
    center = f"/@{lat},{lng},16z" if lat is not None and lng is not None else ""
    return f"https://www.google.com/maps/search/{quote(query)}{center}?hl=tr"


def _read_reviews(page, profile: DirectoryProfile) -> None:
    tab = page.locator('button[role="tab"]', has_text="Yorumlar")
    if not tab.count():
        return
    tab.first.click()
    page.wait_for_timeout(2200)
    # en yeniye göre sırala (yorum tarihi/yanıt oranı "en yeni" yorumlar üzerinden anlamlıdır)
    try:
        sorter = page.get_by_text("En alakalı", exact=True)
        if sorter.count():
            sorter.first.click()
            page.wait_for_timeout(700)
            newest = page.locator('div[role="menuitemradio"]', has_text="En yeni")
            if newest.count():
                newest.first.click()
                page.wait_for_timeout(2000)
                profile.reviews_sort = "En yeni"
            else:
                profile.reviews_sort = "En alakalı"
        else:
            profile.reviews_sort = "En alakalı"
    except Exception:  # sıralama arayüzü değişmiş olabilir; yorumlar yine de okunur
        profile.reviews_sort = profile.reviews_sort or "En alakalı"
    raw = page.evaluate(_REVIEWS_JS)
    profile.reviews, profile.last_review_at, profile.last_review_relative, profile.owner_replies = parse_reviews(raw)
    profile.reviews_sampled = len(profile.reviews)


def _read_about(page, profile: DirectoryProfile) -> None:
    tab = page.locator('button[role="tab"]', has_text="Hakkında")
    if not tab.count():
        return
    tab.first.click()
    page.wait_for_timeout(1500)
    panel = page.locator('div[role="main"]')
    text = panel.first.inner_text() if panel.count() else ""
    profile.about_text = text.strip() or None
    profile.attributes, profile.description = parse_about_text(text)


def _read_cover_photo_date(page, profile: DirectoryProfile) -> None:
    overview = page.locator('button[role="tab"]', has_text="Genel Bakış")
    if overview.count():
        overview.first.click()
        page.wait_for_timeout(1200)
    hero = page.locator('button[aria-label*="fotoğrafı"]')
    if not hero.count():
        return
    hero.first.click()
    page.wait_for_timeout(2200)
    match = re.search(r"Fotoğraf\s*-\s*((?:Oca|Şub|Mar|Nis|May|Haz|Tem|Ağu|Eyl|Eki|Kas|Ara)\w*\s+\d{4})", page.inner_text("body"))
    profile.cover_photo_date = match.group(1) if match else None


def read_place(page, *, deep: bool = True) -> DirectoryProfile:
    """Açık olan yer sayfasını okur. deep=True: yorumlar, hakkında ve kapak fotoğrafı da okunur."""
    profile = parse_place_payload(page.evaluate(_PLACE_JS))
    if deep and profile.name:
        for reader in (_read_about, _read_reviews, _read_cover_photo_date):
            try:
                reader(page, profile)
            except SourceBlocked:
                raise
            except Exception:  # bir alt bölüm okunamazsa (arayüz değişikliği) diğerleri yine denenir; alan None kalır
                continue
    return profile


def lookup(query: BusinessQuery, *, deep: bool = True) -> tuple[DirectoryProfile | None, list[MapsCandidate], str]:
    """İşletmeyi Google Haritalar'da arar ve GÜVENLE eşleşen profili döndürür.

    Döndürür: (profil | None, incelenen adaylar, açıklama). SourceBlocked/SourceError çağırana yükselir.
    """
    place_queries = [f"{query.name} {query.place} {query.city}".strip()]
    if query.city and query.city != query.place:
        place_queries.append(f"{query.name} {query.city}")
    place_queries = list(dict.fromkeys(q.strip() for q in place_queries))

    all_candidates: list[MapsCandidate] = []
    with source_lock(SOURCE), browser_page() as page:
        if query.google_url:
            # Google keşfinde bulunan işletme: yerin kendi adresi doğrudan açılır (adla yeniden arama yapılmaz)
            guarded_goto(page, query.google_url, SOURCE, wait_ms=2500)
            if _wait_view(page) == "place":
                _settle_place_url(page)
                profile = read_place(page, deep=False)
                profile.match = score_match(query, name=profile.name, lat=profile.lat, lng=profile.lng, phone=profile.phone,
                                            address=profile.address, website=profile.website)
                all_candidates.append(MapsCandidate(name=profile.name or "", url=profile.url or "", lat=profile.lat, lng=profile.lng, match=profile.match))
                if profile.match.accepted:
                    if deep:
                        profile = _finish_deep(page, profile)
                    return profile, all_candidates, f"Google Haritalar'da işletmenin kendi sayfası açıldı ({', '.join(profile.match.signals)})."

        for text_query in place_queries:
            guarded_goto(page, _search_url(text_query, query.lat, query.lng), SOURCE, wait_ms=2500)
            view = _wait_view(page)
            if view == "none":
                continue

            if view == "place":
                _settle_place_url(page)
                profile = read_place(page, deep=False)
                profile.match = score_match(
                    query, name=profile.name, lat=profile.lat, lng=profile.lng, phone=profile.phone, address=profile.address, website=profile.website
                )
                all_candidates.append(MapsCandidate(name=profile.name or "", url=profile.url or "", lat=profile.lat, lng=profile.lng,
                                                    rating=profile.rating, review_count=profile.review_count, category=profile.category,
                                                    address=profile.address, phone=profile.phone, match=profile.match))
                if profile.match.accepted:
                    if deep:
                        profile = _finish_deep(page, profile)
                    return profile, all_candidates, f"Google Haritalar'da eşleşen kayıt bulundu ({', '.join(profile.match.signals)})."
                continue

            # sonuç listesi: adayları puanla, en iyisini aç
            candidates = [parse_feed_card(c) for c in page.evaluate(_FEED_JS)[:MAX_CANDIDATES]]
            for cand in candidates:
                cand.match = score_match(query, name=cand.name, lat=cand.lat, lng=cand.lng, phone=cand.phone, address=cand.address)
            all_candidates.extend(candidates)
            viable = sorted((c for c in candidates if c.match and c.match.accepted), key=lambda c: -c.match.score)
            if not viable:
                continue
            best = viable[0]
            guarded_goto(page, best.url, SOURCE, wait_ms=2500)
            if _wait_view(page) != "place":
                continue
            _settle_place_url(page)
            profile = read_place(page, deep=False)
            # detay sayfasında (tam telefon/adres/web sitesiyle) eşleşme TEKRAR doğrulanır
            profile.match = score_match(
                query, name=profile.name, lat=profile.lat, lng=profile.lng, phone=profile.phone, address=profile.address, website=profile.website
            )
            if not profile.match.accepted:
                continue
            if deep:
                profile = _finish_deep(page, profile)
            note = f"Google Haritalar'da eşleşen kayıt bulundu ({', '.join(profile.match.signals)})."
            if len(viable) > 1:
                note += f" Not: {len(viable) - 1} benzer aday daha vardı; en yüksek skorlusu seçildi."
            return profile, all_candidates, note

    return None, all_candidates, "Google Haritalar'da bu işletmeyle güvenle eşleşen bir kayıt bulunamadı."


def _finish_deep(page, profile: DirectoryProfile) -> DirectoryProfile:
    """Eşleşme kabul edildikten sonra yorum/hakkında/fotoğraf bölümlerini okur (profil nesnesi güncellenir)."""
    match = profile.match
    deep = read_place(page, deep=True)
    deep.match = match
    # deep okuma aynı sayfadan yapıldığı için temel alanlar aynıdır; tutarlılık için deep sonucu esas alınır
    return deep


# ----------------------------------------------------------------------------- işletme KEŞFİ (liste araması)
MAX_SCROLLS = 10
_END_OF_LIST_MARKERS = ("Listenin sonuna ulaştınız", "Listenin sonuna ulastiniz", "You've reached the end of the list")


def place_id_from_url(url: str | None) -> str | None:
    match = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", url or "")
    return match.group(1) if match else None


def search_places(text_query: str, lat: float | None, lng: float | None, *, want: int) -> list[MapsCandidate]:
    """Google Haritalar'da 'sektör + ilçe + il' araması yapıp sonuç listesini (kaydırarak) okur.

    Her sonuç gerçek bir Google kaydıdır: ad, puan, yorum sayısı, kategori, adres (kısmi), telefon, koordinat (!3d..!4d) ve
    Haritalar bağlantısı. Engel (CAPTCHA/consent) görülürse SourceBlocked yükselir; aşılmaz. Sonuç yoksa boş liste döner.
    """
    seen: set[str] = set()
    candidates: list[MapsCandidate] = []
    with source_lock(SOURCE), browser_page() as page:
        guarded_goto(page, _search_url(text_query, lat, lng), SOURCE, wait_ms=2500)
        view = _wait_view(page)
        if view == "place":
            # tek sonuç doğrudan yer sayfasına düştü: bu tek işletme döndürülür
            _settle_place_url(page)
            profile = read_place(page, deep=False)
            if profile.name:
                candidates.append(MapsCandidate(name=profile.name, url=profile.url or "", lat=profile.lat, lng=profile.lng, rating=profile.rating,
                                                review_count=profile.review_count, category=profile.category, address=profile.address, phone=profile.phone))
            return candidates
        if view != "feed":
            return []

        feed = page.locator('div[role="feed"]')
        for _ in range(MAX_SCROLLS + 1):
            for card in page.evaluate(_FEED_JS):
                candidate = parse_feed_card(card)
                key = place_id_from_url(candidate.url) or candidate.url
                if key and key not in seen:
                    seen.add(key)
                    candidates.append(candidate)
            if len(candidates) >= want:
                break
            try:
                if any(marker in feed.inner_text() for marker in _END_OF_LIST_MARKERS):
                    break
                feed.evaluate("e => e.scrollTo(0, e.scrollHeight)")
            except Exception:
                break
            page.wait_for_timeout(1600)
    return candidates
