"""DEMO/mock discovery provider — gerçek Google verisi DEĞİLDİR.

Amaç: Google API anahtarı olmadan Discovery akışının uçtan uca (job oluşturma,
normalize etme, tekilleştirme, partial failure) test edilebilmesi. Üretilen
işletmeler tamamen kurgusaldır; hiçbir gerçek işletmeyi temsil etmez.

Deterministik davranış (aynı region+sector+target_count için hep aynı sonuç):
- her 5. deneme (index % 5 == 4) başarısız sayılır → item_errors'a düşer
- her 8. deneme (index % 8 == 7) ilk başarılı sonucun aynısını (aynı external_ref)
  tekrar döndürür → Discovery pipeline'ın dedup mantığını gerçekçi biçimde test eder
"""

import hashlib

from packages.db.models import Region, Sector
from services.integrations.google_places.base import PlaceResult, PlacesProvider, SearchOutcome

NAME_TEMPLATES = [
    "{region} Sofrası",
    "{region} Lezzet Durağı",
    "Anadolu {sector_word}",
    "{region} Konağı",
    "Ege Mutfağı {region}",
    "Şen {sector_word}",
    "{region} Merkez {sector_word}",
    "Kardeşler {sector_word}",
    "Palace {sector_word}",
    "{region} Bahçe {sector_word}",
]

FAILURE_REASONS = [
    "Place Details alınamadı (simulated timeout)",
    "Geçersiz/eksik adres verisi (simulated)",
]


def _sector_word(sector_name: str) -> str:
    return sector_name.split("/")[0].strip().split(" ")[0] if sector_name else "İşletme"


def _mock_place_id(region_name: str, sector_name: str, index: int) -> str:
    raw = f"mock:{region_name}:{sector_name}:{index}"
    return "mock_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class MockPlacesProvider(PlacesProvider):
    name = "mock_demo"
    is_demo_data = True

    def search(self, *, region: Region, sector: Sector, target_count: int) -> SearchOutcome:
        region_name, sector_name = region.name, sector.name
        items: list[PlaceResult] = []
        sector_word = _sector_word(sector_name)
        first_success_ref: str | None = None

        for i in range(target_count):
            is_failure = i % 5 == 4
            is_duplicate = (not is_failure) and i % 8 == 7 and first_success_ref is not None

            if is_failure:
                items.append(
                    PlaceResult(
                        external_ref=_mock_place_id(region_name, sector_name, i),
                        success=False,
                        error_reason=FAILURE_REASONS[i % len(FAILURE_REASONS)],
                    )
                )
                continue

            if is_duplicate:
                items.append(
                    PlaceResult(
                        external_ref=first_success_ref,
                        success=True,
                        name=None,  # gerçek sağlayıcılarda da tekrar sonuçlar aynı veriyi taşır; task normalize eder
                        categories=[sector_name],
                    )
                )
                continue

            template = NAME_TEMPLATES[i % len(NAME_TEMPLATES)]
            name = template.format(region=region_name, sector_word=sector_word)
            ref = _mock_place_id(region_name, sector_name, i)
            if first_success_ref is None:
                first_success_ref = ref

            has_website = i % 3 != 0  # ~1/3'ünde website yok — evidence-based finding'i test etmek için
            items.append(
                PlaceResult(
                    external_ref=ref,
                    success=True,
                    name=name,
                    address=f"{region_name} Merkez Mah. No:{10 + i}, {region_name}",
                    lat=40.75 + (i * 0.001),
                    lng=30.35 + (i * 0.001),
                    phone=f"0500 000 {10 + i:02d} 00",
                    website=f"https://example-demo-{i}.invalid" if has_website else None,
                    rating=round(3.2 + (i % 5) * 0.35, 1),
                    review_count=5 + i * 11,
                    photo_count=i % 6,
                    categories=[sector_name],
                )
            )

        return SearchOutcome(provider_name=self.name, is_demo_data=True, items=items)
