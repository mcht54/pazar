"""Discovery provider arayüzü.

DISCOVERY_PROVIDER=mock  -> MockPlacesProvider (internet/API anahtarı gerekmez)
DISCOVERY_PROVIDER=google -> GooglePlacesProvider (GOOGLE_PLACES_API_KEY gerekir)

Discovery pipeline sadece bu arayüze (PlacesProvider.search) bağımlıdır; hangi
provider kullanıldığı worker/task kodunu hiç etkilemez.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PlaceResult:
    """Tek bir Discovery sonucu. success=False ise diğer alanlar eksik/None olabilir."""

    external_ref: str
    success: bool
    error_reason: str | None = None

    name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    photo_count: int | None = None
    categories: list[str] = field(default_factory=list)


@dataclass
class SearchOutcome:
    provider_name: str
    is_demo_data: bool
    items: list[PlaceResult]


class PlacesProvider(ABC):
    name: str = "unknown"
    is_demo_data: bool = False

    @abstractmethod
    def search(self, *, region_name: str, sector_name: str, target_count: int) -> SearchOutcome:
        """Belirtilen bölge/sektör için en az target_count başarılı sonuç toplamaya çalışır.

        Başarısız tekil kayıtlar (success=False) da listeye dahil edilir — çağıran taraf
        (Celery task) bunları item_errors'a işler, tüm job'u başarısız saymaz.
        """
        raise NotImplementedError
