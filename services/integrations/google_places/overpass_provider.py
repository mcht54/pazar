"""OpenStreetMap Overpass API üzerinden GERÇEK işletme keşfi — API anahtarı gerekmez.

Neden Overpass: Google Places API için ücretli/faturalı bir hesap gerekiyor ve kullanıcının
henüz bir anahtarı yok. Google Maps'i scrape etmek ise kullanım şartlarını ihlal eder ve bu
projede kesinlikle kullanılmaz. OpenStreetMap, tam da bu tür programatik sorgular için var
olan resmi bir sorgu servisi (Overpass API) sunar; veri ODbL lisanslıdır, ticari/kişisel
kullanım serbesttir, tek şart attribution ("© OpenStreetMap contributors").

Dürüstlük notu: OSM'de Google'daki gibi "rating"/"review_count" alanı YOKTUR. Bu alanlar
bu sağlayıcı için her zaman None/not_available olarak bırakılır — asla tahmin edilmez.
Ayrıca OSM veri kapsamı bölgeye ve sektöre göre değişir; küçük ilçelerde/niş sektörlerde
sonuç bulunamaması normaldir ve bir hata değildir.

Nezaket kuralı (Overpass fair-use policy): tek sorguda tüm etiket/anahtar-kelime
alternatifleri birleştirilir (region+sektör başına TEK istek), art arda isteklerde
minimum bekleme uygulanır, sunucu tarafı geçici hatalarda (503/timeout) backoff ile
yeniden denenir.
"""

import re
import time

import httpx

from packages.db.models import Region, Sector
from services.integrations.google_places.base import PlaceResult, PlacesProvider, SearchOutcome

# Birden fazla resmi Overpass aynası — ana sunucu meşgul/rate-limit uygularsa otomatik
# olarak diğerine geçilir. Bu, Overpass topluluğunun kendi önerdiği bir dayanıklılık
# pratiğidir (bkz. https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances).
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_INTERNAL_TIMEOUT_SECONDS = 40
REQUEST_TIMEOUT_SECONDS = 50.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 3.0
MIN_INTERVAL_BETWEEN_REQUESTS_SECONDS = 2.0
WIDE_SEARCH_MULTIPLIER = 2.5
WIDE_SEARCH_MAX_RADIUS_M = 20000
USER_AGENT = "MchttasarimMarketingOS/0.1 (local use; +https://mchttasarim.com)"

_last_request_at: float = 0.0


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_INTERVAL_BETWEEN_REQUESTS_SECONDS:
        time.sleep(MIN_INTERVAL_BETWEEN_REQUESTS_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def _build_query(lat: float, lng: float, radius_m: int, osm_tags: list[str], keywords: list[str]) -> str:
    clauses = []
    for tag in osm_tags:
        if "=" not in tag:
            continue
        key, value = tag.split("=", 1)
        clauses.append(f'node["{key}"="{value}"](around:{radius_m},{lat},{lng});')
        clauses.append(f'way["{key}"="{value}"](around:{radius_m},{lat},{lng});')

    if keywords:
        # Not: regex ("~") araması Overpass'ta etiket indeksini kullanamaz, bu yüzden
        # tag bazlı aramadan çok daha yavaştır. Maliyeti kontrol altında tutmak için
        # sadece node üzerinde (way'de değil) ve tek bir alternation olarak çalıştırılır.
        pattern = "|".join(re.escape(k) for k in keywords)
        clauses.append(f'node["name"~"{pattern}",i](around:{radius_m},{lat},{lng});')

    if not clauses:
        raise ValueError("Sektör için ne osm_tags ne de keyword_variants tanımlı — sorgu oluşturulamaz.")

    body = "\n  ".join(clauses)
    return f"[out:json][timeout:{OVERPASS_INTERNAL_TIMEOUT_SECONDS}];\n(\n  {body}\n);\nout center tags;"


def _extract_address(tags: dict) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = []
    if tags.get("addr:street"):
        street = tags["addr:street"]
        if tags.get("addr:housenumber"):
            street += f" No:{tags['addr:housenumber']}"
        parts.append(street)
    if tags.get("addr:neighbourhood"):
        parts.append(tags["addr:neighbourhood"])
    if tags.get("addr:district"):
        parts.append(tags["addr:district"])
    if tags.get("addr:city"):
        parts.append(tags["addr:city"])
    return ", ".join(parts) if parts else None


def _extract_category(tags: dict) -> str | None:
    for key in ("amenity", "shop", "office", "craft", "tourism", "leisure", "healthcare"):
        if tags.get(key):
            return tags[key]
    return None


class OverpassProvider(PlacesProvider):
    name = "osm_overpass"
    is_demo_data = False

    def _request(self, query: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            endpoint = OVERPASS_ENDPOINTS[(attempt - 1) % len(OVERPASS_ENDPOINTS)]
            _throttle()
            try:
                response = httpx.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 429:
                    # Overpass fair-use rate limiti — kısa aralıklı yeniden deneme yerine
                    # Retry-After'a (yoksa uzun bir varsayılana) uyulur.
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 20.0
                    last_exc = RuntimeError("Overpass API 429: rate limit (fair-use policy)")
                    if attempt < MAX_RETRIES:
                        time.sleep(wait_seconds)
                    continue
                last_exc = RuntimeError(f"Overpass API {response.status_code}: {response.text[:300]}")
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.RequestError) as exc:
                last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_BASE_SECONDS * attempt)
        raise RuntimeError(
            f"OpenStreetMap Overpass API'ye {MAX_RETRIES} denemeden sonra ulaşılamadı: {last_exc}"
        )

    def _parse_elements(self, elements: list[dict], seen_refs: set[str], items: list[PlaceResult], target_count: int) -> None:
        for el in elements:
            tags = el.get("tags") or {}
            name = tags.get("name")
            if not name:
                continue  # isimsiz OSM kaydı kullanılabilir bir işletme değil, sessizce atlanır

            external_ref = f"osm_{el['type']}_{el['id']}"
            if external_ref in seen_refs:
                continue
            seen_refs.add(external_ref)

            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lng = el.get("lon") or (el.get("center") or {}).get("lon")

            items.append(
                PlaceResult(
                    external_ref=external_ref,
                    success=True,
                    name=name,
                    address=_extract_address(tags),
                    lat=lat,
                    lng=lng,
                    phone=tags.get("phone") or tags.get("contact:phone"),
                    website=tags.get("website") or tags.get("contact:website") or tags.get("url"),
                    email=tags.get("email") or tags.get("contact:email"),
                    rating=None,  # OSM'de rating verisi yok — asla tahmin edilmez
                    review_count=None,  # OSM'de review_count verisi yok — asla tahmin edilmez
                    photo_count=None,
                    opening_hours=tags.get("opening_hours"),
                    categories=[c for c in [_extract_category(tags)] if c],
                )
            )
            if len(items) >= target_count:
                return

    def search(self, *, region: Region, sector: Sector, target_count: int, on_batch=None) -> SearchOutcome:
        osm_tags = sector.google_place_types or []
        keywords = sector.keyword_variants or []

        seen_refs: set[str] = set()
        items: list[PlaceResult] = []

        query = _build_query(region.center_lat, region.center_lng, region.search_radius_m, osm_tags, keywords)
        data = self._request(query)
        before = len(items)
        self._parse_elements(data.get("elements", []), seen_refs, items, target_count)
        if on_batch and len(items) > before:
            on_batch(items[before:])

        # Sonuç istenenden az geldiyse ve yarıçap büyütmeye uygunsa TEK bir ek deneme ile
        # arama alanını genişlet (ör. küçük bir ilçede gerçekten az işletme tagli olabilir).
        # Bu, "10 istedim 1 geldi" durumunda kodun elinden geleni yapmasını sağlar; OSM'de
        # o kategori için gerçekten veri yoksa yine de az sonuçla dönmek dürüst olan davranıştır.
        if len(items) < target_count and region.search_radius_m < WIDE_SEARCH_MAX_RADIUS_M:
            wider_radius = min(region.search_radius_m * WIDE_SEARCH_MULTIPLIER, WIDE_SEARCH_MAX_RADIUS_M)
            wider_query = _build_query(region.center_lat, region.center_lng, int(wider_radius), osm_tags, keywords)
            wider_data = self._request(wider_query)
            before = len(items)
            self._parse_elements(wider_data.get("elements", []), seen_refs, items, target_count)
            if on_batch and len(items) > before:
                on_batch(items[before:])

        return SearchOutcome(provider_name=self.name, is_demo_data=False, items=items)
