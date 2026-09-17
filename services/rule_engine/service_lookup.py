from sqlalchemy.orm import Session

from packages.db.models import ServiceCatalog


def resolve_service_ids(db: Session, service_names: tuple[str, ...]) -> list[int]:
    if not service_names:
        return []
    rows = db.query(ServiceCatalog).filter(ServiceCatalog.service_name.in_(service_names)).all()
    found_by_name = {row.service_name: row.id for row in rows}
    missing = [name for name in service_names if name not in found_by_name]
    if missing:
        raise RuntimeError(
            f"services_catalog içinde bulunamayan hizmet(ler): {missing}. Önce `python -m packages.db.seed` çalıştırılmalı."
        )
    return [found_by_name[name] for name in service_names]
