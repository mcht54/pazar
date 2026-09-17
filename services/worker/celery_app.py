from celery import Celery

from packages.config import settings

celery_app = Celery(
    "mchttasarim_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "services.worker.tasks.discovery",
        "services.worker.tasks.analysis",
        "services.worker.tasks.proposal",
        "services.worker.tasks.reporting",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Istanbul",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)
