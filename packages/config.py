from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"

    database_url: str = "postgresql+psycopg://mchttasarim:mchttasarim@localhost:5432/mchttasarim_dev"
    redis_url: str = "redis://localhost:6379/0"

    api_secret_key: str = "change-me-in-real-env"
    api_cors_origins: str = "http://localhost:3000"

    anthropic_api_key: str = ""
    google_places_api_key: str = ""
    google_pagespeed_api_key: str = ""

    discovery_provider: str = "mock"  # mock | google
    ai_provider: str = "none"  # none | claude — ANTHROPIC_API_KEY yoksa "none" kalmalı

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


settings = Settings()
