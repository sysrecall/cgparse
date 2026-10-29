"""Producer-only Celery client: the api never runs workers, it only enqueues."""

from functools import lru_cache
from uuid import UUID

from app_core.settings import get_shared_settings
from celery import Celery

ROUTE_TASK = "processing.route_document"
EXTRACT_TASK = "processing.extract_document"
VALIDATE_TASK = "processing.validate_document"


@lru_cache
def get_producer() -> Celery:
    return Celery(broker=get_shared_settings().redis_url)


def enqueue_route(document_id: UUID, from_stage: str = "parse") -> None:
    """Fire-and-forget: the message waits in the ocr queue until workers exist."""
    get_producer().send_task(ROUTE_TASK, args=[str(document_id), from_stage], queue="ocr")


def enqueue_extract(document_id: UUID) -> None:
    """Re-run extraction only (skip parsing) — used by reprocess?from=extract."""
    get_producer().send_task(EXTRACT_TASK, args=[str(document_id)], queue="llm")


def enqueue_validate(document_id: UUID) -> None:
    """Re-run validation only — used after a human correction is saved."""
    get_producer().send_task(VALIDATE_TASK, args=[str(document_id)], queue="llm")
