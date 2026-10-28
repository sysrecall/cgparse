"""Producer-only Celery client: the api never runs workers, it only enqueues."""

from functools import lru_cache
from uuid import UUID

from celery import Celery

from app_core.settings import get_shared_settings

ROUTE_TASK = "processing.route_document"


@lru_cache
def get_producer() -> Celery:
    return Celery(broker=get_shared_settings().redis_url)


def enqueue_route(document_id: UUID) -> None:
    """Fire-and-forget: the message waits in the ocr queue until workers exist."""
    get_producer().send_task(ROUTE_TASK, args=[str(document_id)], queue="ocr")
