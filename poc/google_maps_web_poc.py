"""PoC (SADECE DENEY, uygulamaya entegre DEĞİL): API anahtarı olmadan Google Maps web
arayüzünden işletme bilgisi okunabilir mi?

Kurallar:
- Her alanın kaynağı ayrı tutulur: "openstreetmap" ve "google_web" hiçbir zaman birleştirilmez.
- Eşleşme, koordinat mesafesi + isim benzerliği ile DOĞRULANIR. Doğrulanamazsa google_web
  alanları BOŞ bırakılır (yanlış işletmeyle eşleştirme/uydurma yok).
- CAPTCHA / "olağandışı trafik" / consent duvarı görülürse tüm çalıştırma DURUR.
  Hiçbir engel aşılmaya çalışılmaz (stealth eklentisi, proxy, CAPTCHA çözme YOK).
- İşletme başına tek arama, aralarında bekleme. Toplam 5 işletme.
"""

import argparse
import difflib
import json
import math
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from packages.db.base import SessionLocal  # noqa: E402
from packages.db.models import Business  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "output"
OUT_DIR.mkdir(exist_ok=True)

# Sakarya -> Adapazarı -> Restoran sonuçlarından seçilen 5 OSM kaydı (business.id)
BUSINESS_IDS = [19, 15, 16, 12, 14]

MAX_MATCH_DISTANCE_M = 300
MIN_NAME_SIMILARITY = 0.6
PAUSE_BETWEEN_BUSINESSES_S = 6


def norm(text: str) -> str:
    text = (text or "").replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def name_similarity(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return round(max(seq, overlap), 2)


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def coords_from_url(url: str):
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def strip_label(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^(Adres|Telefon|Web sitesi)\s*:\s*", "", value.strip()).strip() or None


def detect_wall(page) -> str | None:
    url = page.url
    if "consent.google" in url:
        return "consent_wall"
    if "/sorry/" in url or "google.com/sorry" in url:
        return "blocked_unusual_traffic"
    body = ""
    try:
        body = page.inner_text("body", timeout=2000).lower()
    except Exception:
        pass
    if "unusual traffic" in body or "olağandışı trafik" in body or "g-recaptcha" in page.content().lower():
        return "blocked_captcha"
    return None


def read_place_panel(page) -> dict:
    def attr(selector, name):
        loc = page.locator(selector).first
        return loc.get_attribute(name, timeout=1500) if loc.count() else None

    name = page.locator("h1").first.inner_text(timeout=3000) if page.locator("h1").count() else None
    address = strip_label(attr('button[data-item-id="address"]', "aria-label"))
    phone_btn = page.locator('button[data-item-id^="phone:tel:"]').first
    phone = strip_label(phone_btn.get_attribute("aria-label", timeout=1500)) if phone_btn.count() else None
    website = attr('a[data-item-id="authority"]', "href")
    return {"name": name, "address": address, "phone": phone, "website": website, "place_url": page.url}


def lookup_google_web(page, biz: dict) -> dict:
    result = {
        "status": "error",
        "source": "google_web",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query_url": None,
        "candidates": [],
        "match": None,
        "data": None,
    }
    url = f"https://www.google.com/maps/search/{quote(biz['name'])}/@{biz['lat']},{biz['lng']},17z?hl=tr"
    result["query_url"] = url
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2500)

    wall = detect_wall(page)
    if wall:
        result["status"] = wall
        return result

    try:
        page.wait_for_selector('div[role="feed"], button[data-item-id="address"]', timeout=15000)
    except PWTimeout:
        wall = detect_wall(page)
        result["status"] = wall or "no_results_or_layout_changed"
        return result

    candidates = []
    if page.locator('div[role="feed"]').count():
        cards = page.locator('div[role="feed"] a.hfpxzc')
        for i in range(min(cards.count(), 6)):
            card = cards.nth(i)
            label = card.get_attribute("aria-label")
            href = card.get_attribute("href") or ""
            c = coords_from_url(href)
            dist = round(haversine_m(biz["lat"], biz["lng"], c[0], c[1])) if c else None
            candidates.append(
                {"index": i, "name": label, "distance_m": dist, "name_similarity": name_similarity(biz["name"], label or "")}
            )
        result["candidates"] = candidates
        viable = [
            c for c in candidates
            if c["distance_m"] is not None and c["distance_m"] <= MAX_MATCH_DISTANCE_M and c["name_similarity"] >= MIN_NAME_SIMILARITY
        ]
        if not viable:
            result["status"] = "unmatched"
            return result
        best = sorted(viable, key=lambda c: (-c["name_similarity"], c["distance_m"]))[0]
        cards.nth(best["index"]).click()
        page.wait_for_selector('button[data-item-id="address"], h1', timeout=15000)
        page.wait_for_timeout(2000)
    # tek sonuç doğrudan yer sayfasına düşmüş olabilir; her iki durumda paneli oku ve TEKRAR doğrula
    panel = read_place_panel(page)
    c = coords_from_url(panel["place_url"])
    dist = round(haversine_m(biz["lat"], biz["lng"], c[0], c[1])) if c else None
    sim = name_similarity(biz["name"], panel["name"] or "")
    result["match"] = {"distance_m": dist, "name_similarity": sim}
    if dist is None or dist > MAX_MATCH_DISTANCE_M or sim < MIN_NAME_SIMILARITY:
        result["status"] = "unmatched"
        return result
    result["status"] = "matched"
    result["data"] = panel
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=len(BUSINESS_IDS))
    args = parser.parse_args()

    db = SessionLocal()
    records = []
    for bid in BUSINESS_IDS[: args.limit]:
        b = db.get(Business, bid)
        records.append(
            {"id": b.id, "osm_ref": b.google_place_id, "name": b.name, "address": b.address,
             "phone": b.phone, "website": b.website, "lat": b.lat, "lng": b.lng}
        )
    db.close()

    output = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="tr-TR", viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        for i, biz in enumerate(records):
            print(f"[{i + 1}/{len(records)}] {biz['name']} ...", flush=True)
            try:
                g = lookup_google_web(page, biz)
            except Exception as exc:  # tek işletme hatası tüm PoC'yi düşürmesin
                g = {"status": f"error:{type(exc).__name__}", "source": "google_web", "data": None}
            page.screenshot(path=str(OUT_DIR / f"{biz['id']}_{g['status']}.png"))
            output.append(
                {
                    "osm": {"source": "openstreetmap", **{k: biz[k] for k in ("osm_ref", "name", "address", "phone", "website", "lat", "lng")}},
                    "google_web": g,
                }
            )
            print(f"    -> {g['status']}", flush=True)
            if g["status"] in ("consent_wall", "blocked_unusual_traffic", "blocked_captcha"):
                print("    !! Engel/consent duvarı görüldü — çalıştırma DURDURULDU, aşılmaya çalışılmadı.")
                break
            time.sleep(PAUSE_BETWEEN_BUSINESSES_S)
        browser.close()

    (OUT_DIR / "poc_result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print("\nYazıldı:", OUT_DIR / "poc_result.json")


if __name__ == "__main__":
    main()
