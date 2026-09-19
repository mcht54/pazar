"""Gerçek Google Places API (New) sağlayıcısı — Text Search (New).

Sadece DISCOVERY_PROVIDER=google iken (ve GOOGLE_PLACES_API_KEY .env'de tanımlıyken)
kullanılır. Anahtar koda asla gömülmez, sadece backend tarafında okunur. Kota/cache/
attribution kuralları integrations_registry tablosundan okunur (bkz. policy.py).

Neden Text Search (New): Nearby Search kategori bazlı sabit "type" listesine bağımlı
ve bizim 55 sektörümüzün çoğu (ör. "Web Tasarım", "Muhasebe") Google'ın resmi place
type listesinde yok. Text Search serbest metin sorgusu + locationBias ile hem tag
hem isim bazlı eşleşmeyi tek istekte kapsıyor ve New API'de asıl önerilen yöntem bu.

Maliyet notu: FieldMask'te istediğimiz alanların çoğu (puan, yorum sayısı, telefon, web sitesi,
çalışma saatleri) Google'ın "Enterprise" SKU'suna giriyor; yorum tarihleri daha da üst bir
SKU'ya girer. Bu yüzden FieldMask gerekenle sınırlı tutulur ve yorum alanı
GOOGLE_PLACES_FETCH_REVIEWS=false ile kapatılabilir.

Google'ın VERMEDİĞİ alanlar (işletme açıklaması, hizmet listesi, son fotoğraf tarihi, yorumlara
işletme yanıtı) bu sağlayıcıda da None kalır ve analizde "Doğrulanamadı" olarak gösterilir.
"""

import time
from datetime import date, datetime

import httpx
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import ApiUsageLedger, Region, Sector
from services.integrations.google_places.base import PlaceResult, PlacesProvider, SearchOutcome
from services.integrations.google_places.policy import load_policy

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.5
PAGE_SIZE = 20  # Google'ın izin verdiği maksimum
MAX_PAGES = 3  # Text Search (New) toplamda en fazla ~60 sonuç (3 sayfa) verir
PAGE_TOKEN_DELAY_SECONDS = 2.0  # bir sonraki sayfa token'ı aktif olana kadar kısa bekleme

_BASE_FIELDS = [
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.regularOpeningHours.weekdayDescriptions",
    "places.businessStatus",
    "places.types",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.googleMapsUri",
    "places.photos.name",  # sadece foto sayısı için — API en fazla 10 fotoğraf döndürür
    "nextPageToken",
]
# Yorum tarihleri (son yorum ne zaman?) daha pahalı bir SKU'ya girer; ayarla kapatılabilir.
_REVIEW_FIELDS = ["places.reviews.publishTime"]


def _field_mask() -> str:
    fields = list(_BASE_FIELDS)
    if settings.google_places_fetch_reviews:
        fields += _REVIEW_FIELDS
    return ",".join(fields)


MAX_PHOTOS_RETURNED = 10  # Google Places (New) bir yer için en fazla 10 fotoğraf referansı döndürür


class GooglePlacesQuotaExceeded(RuntimeError):
    pass


class GooglePlacesProvider(PlacesProvider):
    name = "google_places"
    is_demo_data = False

    def __init__(self, db: Session):
        self.db = db
        self.policy = load_policy(db)

    def _check_quota(self) -> None:
        daily_cap = self.policy.quota_config.get("daily_request_cap")
        if not daily_cap:
            return
        today = date.today().isoformat()
        used = (
            self.db.query(ApiUsageLedger)
            .filter(ApiUsageLedger.integration_name == "google_places", ApiUsageLedger.quota_period == today)
            .count()
        )
        if used >= daily_cap:
            raise GooglePlacesQuotaExceeded(
                f"Günlük Google Places kotası doldu ({used}/{daily_cap}). "
                "integrations_registry.quota_config üzerinden ayarlanabilir."
            )

    def _log_usage(self, endpoint: str) -> None:
        self.db.add(
            ApiUsageLedger(
                integration_name="google_places",
                endpoint=endpoint,
                cost_units=1.0,
                quota_period=date.today().isoformat(),
            )
        )
        self.db.commit()

    def _post_with_retry(self, body: dict) -> dict:
        last_exc: Exception | None = None
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_places_api_key,
            "X-Goog-FieldMask": _field_mask(),
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = httpx.post(SEARCH_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
                if response.status_code == 200:
                    self._log_usage("places:searchText")
                    return response.json()
                if response.status_code == 429 or response.status_code >= 500:
                    last_exc = RuntimeError(f"Google Places {response.status_code}: {response.text[:300]}")
                else:
                    # 400/401/403 gibi kalıcı hatalar (geçersiz anahtar, kota, hatalı istek) — tekrar denemenin anlamı yok
                    raise RuntimeError(f"Google Places API hatası {response.status_code}: {response.text[:300]}")
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RequestError) as exc:
                last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        raise RuntimeError(f"Google Places isteği {MAX_RETRIES} denemeden sonra başarısız: {last_exc}")

    def _parse_place(self, place: dict) -> PlaceResult:
        location = place.get("location") or {}
        opening_hours = None
        weekday_desc = (place.get("regularOpeningHours") or {}).get("weekdayDescriptions")
        if weekday_desc:
            opening_hours = "; ".join(weekday_desc)

        photos = place.get("photos")
        photo_count = len(photos) if photos is not None else 0
        # API en fazla 10 fotoğraf verir: 10 geldiyse gerçek sayı "en az 10"dur.
        photos_capped = photo_count >= MAX_PHOTOS_RETURNED

        reviews = place.get("reviews") or []
        review_times = []
        for review in reviews:
            published = review.get("publishTime")
            if published:
                try:
                    review_times.append(datetime.fromisoformat(published.replace("Z", "+00:00")))
                except ValueError:
                    continue
        last_review_at = max(review_times) if review_times else None

        types = place.get("types", [])
        return PlaceResult(
            external_ref=f"google_{place['id']}",
            success=True,
            name=(place.get("displayName") or {}).get("text"),
            address=place.get("formattedAddress"),
            lat=location.get("latitude"),
            lng=location.get("longitude"),
            phone=place.get("nationalPhoneNumber"),
            website=place.get("websiteUri"),
            rating=place.get("rating"),
            review_count=place.get("userRatingCount"),
            photo_count=photo_count,
            photos_capped=photos_capped,
            opening_hours=opening_hours,
            categories=types,
            category_label=(place.get("primaryTypeDisplayName") or {}).get("text"),
            maps_url=place.get("googleMapsUri"),
            source_url=place.get("googleMapsUri"),
            last_review_at=last_review_at,
            reviews_sampled=len(reviews) if settings.google_places_fetch_reviews else None,
            profile={
                "primary_type": place.get("primaryType"),
                "types": types,
                "business_status": place.get("businessStatus"),
            },
        )

    def search(self, *, region: Region, sector: Sector, target_count: int, on_batch=None) -> SearchOutcome:
        if not settings.google_places_api_key:
            raise RuntimeError(
                "GOOGLE_PLACES_API_KEY tanımlı değil. DISCOVERY_PROVIDER=google kullanmak için "
                ".env dosyasına gerçek bir anahtar eklenmeli. Anahtar yoksa DISCOVERY_PROVIDER=osm kullanın."
            )

        self._check_quota()

        text_query = f"{sector.name} {region.name}"
        items: list[PlaceResult] = []
        seen_refs: set[str] = set()
        page_token: str | None = None

        for page in range(MAX_PAGES):
            if len(items) >= target_count:
                break

            body = {
                "textQuery": text_query,
                "languageCode": "tr",
                "pageSize": PAGE_SIZE,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": region.center_lat, "longitude": region.center_lng},
                        "radius": float(region.search_radius_m),
                    }
                },
            }
            if page_token:
                body["pageToken"] = page_token

            data = self._post_with_retry(body)
            places = data.get("places", [])

            batch: list[PlaceResult] = []
            for place in places:
                ref = f"google_{place['id']}"
                if ref in seen_refs:
                    continue
                seen_refs.add(ref)
                parsed = self._parse_place(place)
                items.append(parsed)
                batch.append(parsed)
                if len(items) >= target_count:
                    break

            if on_batch and batch:
                on_batch(batch)

            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(PAGE_TOKEN_DELAY_SECONDS)

        return SearchOutcome(provider_name=self.name, is_demo_data=False, items=items)
