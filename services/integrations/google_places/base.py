"""Discovery provider arayüzü.

DISCOVERY_PROVIDER=google_maps -> GoogleMapsProvider (VARSAYILAN, gerçek Google Haritalar verisi, API anahtarı gerekmez)
DISCOVERY_PROVIDER=mock   -> MockPlacesProvider (SADECE test/geliştirme — gerçek veri değildir)
DISCOVERY_PROVIDER=google -> GooglePlacesProvider (GOOGLE_PLACES_API_KEY gerekir, henüz tamamlanmadı)

Discovery pipeline sadece bu arayüze (PlacesProvider.search) bağımlıdır; hangi
provider kullanıldığı worker/task kodunu hiç etkilemez. search() bölge/sektörün
kendi ORM kayıtlarını alır (isim string'i değil) — gerçek sağlayıcıların koordinat/
etiket gibi ek bilgiye ihtiyacı var; mock provider bunları basitçe yok sayar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from packages.db.models import Region, Sector

OnBatch = Callable[[list["PlaceResult"]], None]


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
    email: str | None = None
    rating: float | None = None
    review_count: int | None = None
    photo_count: int | None = None
    opening_hours: str | None = None  # kullanıcıya gösterilecek (Türkçe) biçim
    categories: list[str] = field(default_factory=list)  # ham kaynak kategorileri (doğrulama/izlenebilirlik için)

    # --- Kaynaktan gelen ek profil verisi. Kaynak vermediyse None kalır — asla tahmin edilmez. ---
    category_label: str | None = None  # kaynaktaki kategorinin Türkçe etiketi
    maps_url: str | None = None  # SADECE kaynak gerçek bir Google Haritalar bağlantısı verdiyse
    source_url: str | None = None  # verinin alındığı kaynak kaydı (ör. OSM node sayfası)
    last_review_at: datetime | None = None
    photos_capped: bool = False  # True ise photo_count "en az bu kadar" demektir (API üst sınırı)
    reviews_sampled: int | None = None  # son yorum tarihi kaç yorum arasından bulundu
    profile: dict = field(default_factory=dict)  # sosyal medya, birincil tür vb. ek alanlar


@dataclass
class SearchOutcome:
    provider_name: str
    is_demo_data: bool
    items: list[PlaceResult]


class PlacesProvider(ABC):
    name: str = "unknown"
    is_demo_data: bool = False

    @abstractmethod
    def search(self, *, region: Region, sector: Sector, target_count: int, on_batch: OnBatch | None = None) -> SearchOutcome:
        """Belirtilen bölge/sektör için en az target_count başarılı sonuç toplamaya çalışır.

        Başarısız tekil kayıtlar (success=False) da listeye dahil edilir — çağıran taraf
        (Celery task) bunları item_errors'a işler, tüm job'u başarısız saymaz.

        on_batch verilirse, sağlayıcı her yeni veri grubunu (ör. Google'da her sayfa,
        Google Haritalar'da her kaydırma/sorgu grubu) elde eder etmez bu callback ile bildirir —
        böylece çağıran taraf sonuçları DB'ye hemen yazıp kullanıcıya arama bitmeden
        gösterebilir (progressive/streaming sonuç).
        """
        raise NotImplementedError
