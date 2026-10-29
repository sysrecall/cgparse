"""Celery application: queue split (ocr | llm) maps 1:1 to worker pools on Render."""

from app_core.settings import get_shared_settings
from celery import Celery

settings = get_shared_settings()


def _celery_redis_url(url: str) -> str:
    """Celery's redis backend refuses rediss:// without an explicit ssl_cert_reqs."""
    if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}ssl_cert_reqs=CERT_REQUIRED"
    return url


celery_app = Celery(
    "processing",
    broker=_celery_redis_url(settings.redis_url),
    backend=_celery_redis_url(settings.redis_url),
)

celery_app.conf.update(
    imports=["app.queues.pipeline"],
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
