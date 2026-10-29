"""Progress events: workers publish here, the api SSE endpoint subscribes."""

import json

import redis
from app_core.settings import get_shared_settings

CHANNEL = "docintel:events"


def publish(event: dict) -> None:
    """Publish a progress event, e.g. {"document_id": ..., "stage": "ocr", "status": "..."}."""
    settings = get_shared_settings()
    client = redis.Redis.from_url(settings.redis_url)
    client.publish(CHANNEL, json.dumps(event))
