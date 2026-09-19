"""Google Haritalar ile GERÇEK işletme keşfi (resmi API ve anahtar OLMADAN) — varsayılan keşif kaynağıdır.

Akış: sektör + ilçe + il aramasıyla Google Haritalar sonuç listesi açılır (gerçek bir Chromium, herkese açık sayfa), kaydırılarak
istenen sayıda işletme okunur. Her sonuç GERÇEK bir Google kaydıdır; koordinat, Haritalar bağlantısı, puan, yorum sayısı, kategori,
telefon ve (kısmi) adres listeden gelir. Web sitesi, tam adres, çalışma saatleri, hakkında bilgileri ve yorumlar sonraki araştırma
aşamasında (services/research) yerin kendi sayfasından okunur.

OpenStreetMap/Overpass bu akışta KULLANILMAZ. Google engel koyarsa (CAPTCHA/consent) durulur ve nedeni açıkça bildirilir; engel
aşılmaya çalışılmaz, veri uydurulmaz. Not: Google'ın kullanım şartları otomatik erişime izin vermez; bu yöntem düşük hacimle,
hız sınırı ve önbellekle, yalnızca kullanıcının talebiyle çalışır.
"""

from packages.db.models import Region, Sector
from services.integrations.google_places.base import PlaceResult, PlacesProvider, SearchOutcome
from services.research import google_maps
from services.research.browser import SourceBlocked, SourceError
from services.research.normalize import haversine_m

# Sonuçlar bölge merkezine bu çarpanla (yarıçap × çarpan) uzaklıktan fazla olamaz; Google bazen şehrin başka yerinden de sonuç verir.
RADIUS_FACTOR = 1.6
MAX_QUERY_VARIANTS = 2


def query_terms(sector: Sector) -> list[str]:
    """Arama ifadeleri: önce sektörün ilk anahtar ifadesi (örn. 'işitme cihazı'), sonra sektör adı."""
    terms = [t.strip() for t in (sector.keyword_variants or []) if t.strip()][:1] + [sector.name.split("/")[0].strip()]
    return list(dict.fromkeys(terms))[:MAX_QUERY_VARIANTS]


class GoogleMapsProvider(PlacesProvider):
    name = "google_maps"
    is_demo_data = False

    def search(self, *, region: Region, sector: Sector, target_count: int, on_batch=None) -> SearchOutcome:
        parent_name = None
        if region.parent_region_id:
            from packages.db.base import SessionLocal

            with SessionLocal() as db:
                parent = db.get(Region, region.parent_region_id)
                parent_name = parent.name if parent else None
        place_text = f"{region.name} {parent_name}" if parent_name else region.name

        items: list[PlaceResult] = []
        seen: set[str] = set()
        try:
            for term in query_terms(sector):
                candidates = google_maps.search_places(f"{term} {place_text}", region.center_lat, region.center_lng, want=target_count)
                batch: list[PlaceResult] = []
                for cand in candidates:
                    ref = google_maps.place_id_from_url(cand.url)
                    if not ref or ref in seen or not cand.name:
                        continue
                    if cand.lat is not None and cand.lng is not None:
                        if haversine_m(region.center_lat, region.center_lng, cand.lat, cand.lng) > region.search_radius_m * RADIUS_FACTOR:
                            continue  # aranan bölgenin dışında
                    seen.add(ref)
                    batch.append(PlaceResult(
                        external_ref=f"gmaps_{ref}", success=True, name=cand.name, address=cand.address, lat=cand.lat, lng=cand.lng,
                        phone=cand.phone, rating=cand.rating, review_count=cand.review_count, category_label=cand.category,
                        maps_url=cand.url, source_url=cand.url, categories=[cand.category] if cand.category else [],
                        profile={"listed_by": "google_maps_search", "query": f"{term} {place_text}"},
                    ))
                batch = batch[: max(0, target_count - len(items))]
                if batch:
                    items.extend(batch)
                    if on_batch:
                        on_batch(batch)
                if len(items) >= target_count:
                    break
        except SourceBlocked as exc:
            raise RuntimeError(
                f"Google Haritalar otomatik erişimi engelledi ({exc.reason}). Engel aşılmaya çalışılmaz; bir süre sonra yeniden deneyin."
            ) from exc
        except SourceError as exc:
            raise RuntimeError(f"Google Haritalar açılamadı: {exc.reason}") from exc
        return SearchOutcome(provider_name=self.name, is_demo_data=False, items=items)
