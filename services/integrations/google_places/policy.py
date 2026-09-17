"""Google Places API (New) kullanım politikası.

Kaynak: integrations_registry tablosu (bkz. packages/db/seed.py) — kota, cache ve
attribution kuralları kodda sabitlenmez, DB'den okunur. Böylece Google'ın kuralları
değiştiğinde tek satırlık bir DB güncellemesi yeterli olur, deploy gerekmez.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from packages.db.models import IntegrationRegistry

INTEGRATION_NAME = "google_places"


@dataclass(frozen=True)
class IntegrationPolicy:
    name: str
    terms_url: str | None
    quota_config: dict
    cache_policy: dict
    requires_oauth: bool
    attribution_requirements: str | None


def load_policy(db: Session) -> IntegrationPolicy:
    row = db.query(IntegrationRegistry).filter_by(name=INTEGRATION_NAME).one_or_none()
    if row is None:
        raise RuntimeError(
            f"'{INTEGRATION_NAME}' için integrations_registry kaydı yok. "
            "Önce `python -m packages.db.seed` çalıştırılmalı."
        )
    return IntegrationPolicy(
        name=row.name,
        terms_url=row.terms_url,
        quota_config=row.quota_config,
        cache_policy=row.cache_policy,
        requires_oauth=row.requires_oauth,
        attribution_requirements=row.attribution_requirements,
    )


# Sprint 1: client.py — bu policy'yi okuyup Nearby/Text Search + Place Details
# çağrılarını yapan, api_usage_ledger'a işleyen ve cache_policy'e göre Redis
# önbellekleme yapan gerçek istemci burada eklenecek.
