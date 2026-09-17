from services.worker.celery_app import celery_app


@celery_app.task(name="worker.ping")
def ping() -> str:
    """Sprint 0 smoke-test task; confirms broker/worker wiring works."""
    return "pong"


# Sprint 1: run_discovery_job(discovery_job_id) — bölge/sektör çözümleme,
# Google Places çağrıları, tekilleştirme, businesses tablosuna yazma.
