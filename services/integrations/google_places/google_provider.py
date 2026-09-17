"""Gerçek Google Places API (New) sağlayıcısı.

Sadece DISCOVERY_PROVIDER=google iken kullanılır. GOOGLE_PLACES_API_KEY .env'den
okunur, koda asla gömülmez. Kota/cache/attribution kuralları integrations_registry
tablosundan okunur (bkz. policy.py) — sabit varsayım yapılmaz.

Not (Sprint 1): Nearby Search + Text Search + Place Details çağrılarının tam
implementasyonu, gerçek bir API anahtarıyla doğrulanana kadar tamamlanmayacak.
Bu dosya; timeout, retry, rate limit ve quota tracking iskeletini sağlar.
"""

import time
from datetime import date

import httpx
from sqlalchemy.orm import Session

from packages.config import settings
from packages.db.models import ApiUsageLedger
from services.integrations.google_places.base import PlacesProvider, SearchOutcome
from services.integrations.google_places.policy import load_policy

REQUEST_TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.5


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

    def _request_with_retry(self, client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Google Places {response.status_code}", request=response.request, response=response
                    )
                return response
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        raise RuntimeError(f"Google Places isteği {MAX_RETRIES} denemeden sonra başarısız: {last_exc}")

    def search(self, *, region_name: str, sector_name: str, target_count: int) -> SearchOutcome:
        if not settings.google_places_api_key:
            raise RuntimeError(
                "GOOGLE_PLACES_API_KEY tanımlı değil. DISCOVERY_PROVIDER=google kullanmak için "
                ".env dosyasına gerçek bir anahtar eklenmeli. Anahtar yoksa DISCOVERY_PROVIDER=mock kullanın."
            )

        self._check_quota()

        # TODO (gerçek API anahtarı elde edilince tamamlanacak):
        #   1. Nearby/Text Search çağrısı (region merkezi + yarıçap, sector -> place type/keyword)
        #   2. Sayfalama (next_page_token)
        #   3. Her aday için Place Details çağrısı (phone, website, rating, review_count, photos)
        #   4. Her başarılı/başarısız çağrı self._log_usage(...) ile api_usage_ledger'a işlenir
        #   5. Place Details sonuçları policy.cache_policy'e göre Redis'te önbelleklenir
        raise NotImplementedError(
            "GooglePlacesProvider henüz tamamlanmadı — gerçek GOOGLE_PLACES_API_KEY ile birlikte "
            "Sprint kapsamında implemente edilecek. Şimdilik DISCOVERY_PROVIDER=mock kullanın."
        )
