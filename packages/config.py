from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"

    database_url: str = "postgresql+psycopg://mchttasarim:mchttasarim@localhost:5432/mchttasarim_dev"
    redis_url: str = "redis://localhost:6379/0"

    api_secret_key: str = "change-me-in-real-env"
    api_cors_origins: str = "http://localhost:3000"
    web_base_url: str = "http://localhost:3000"  # e-postadaki şifre bağlantılarının adresi (arayüzün genel adresi)
    session_days: int = 7  # oturum, son kullanımdan itibaren bu kadar gün geçerli (kayan süre)
    session_max_days: int = 30  # oturumun mutlak üst sınırı ('Beni hatırla' işaretsiz)
    remember_days: int = 30  # 'Beni hatırla' işaretliyse kalıcı çerez ve kayan oturum süresi
    remember_max_days: int = 90  # 'Beni hatırla' oturumunun mutlak üst sınırı

    anthropic_api_key: str = ""
    google_places_api_key: str = ""
    # Places API (New) Text Search adresi. Yalnızca test/yerel ortamlarda (Google'a istek atmadan sahte sunucuya yönlendirmek için) değiştirilir.
    google_places_search_url: str = "https://places.googleapis.com/v1/places:searchText"
    google_pagespeed_api_key: str = ""
    research_enabled: bool = True  # Google/Bing Haritalar + web sitesi + sosyal medya araştırması (RESEARCH_ENABLED=false ile kapatılır; testler kapatır)
    google_places_fetch_reviews: bool = True  # son yorum tarihi için (daha pahalı SKU) — kapatılabilir

    discovery_provider: str = "google_maps"  # google_maps (varsayılan, anahtarsız) | google (Places API) | mock (sadece test)
    ai_provider: str = "none"  # none | claude — ANTHROPIC_API_KEY yoksa "none" kalmalı

    @field_validator("discovery_provider", mode="before")
    @classmethod
    def _legacy_provider_names(cls, value):
        """Eski .env dosyalarında kalan 'osm'/'overpass' değeri uygulamayı bozmasın: OpenStreetMap/Overpass artık kullanılmıyor."""
        if isinstance(value, str) and value.strip().lower() in ("osm", "overpass", "openstreetmap"):
            return "google_maps"
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


settings = Settings()
