"""Celery application: queue split (ocr | llm) maps 1:1 to worker pools on Render."""

from celery import Celery

from app_core.settings import get_shared_settings

settings = get_shared_settings()

celery_app = Celery(
    "processing",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_queues={
        "ocr": {"exchange": "ocr", "routing_key": "ocr"},
        "llm": {"exchange": "llm", "routing_key": "llm"},
    },
    task_default_queue="ocr",
    task_acks_late=True,          # crash-safe: task re-delivered if a worker dies mid-job
    worker_prefetch_multiplier=1,  # long tasks: don't hoard the queue
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)
