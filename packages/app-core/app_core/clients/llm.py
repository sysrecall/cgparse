"""LLM client (OpenAI-compatible; NVIDIA NIM by default) + JSON completion helper."""

import json
import re
import time
from functools import lru_cache

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app_core.settings import get_processing_settings

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0

# Transient provider failures worth a second try. 404 is normally a hard "model
# not found", but this provider returns it spuriously under load -- measured at
# 1 in 5 calls on an otherwise healthy model -- and a retry clears it.
RETRYABLE_STATUS = frozenset({404, 408, 409, 429, 500, 502, 503, 504})
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, APIStatusError)


@lru_cache
def get_llm_client() -> OpenAI:
    settings = get_processing_settings()
    return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


# Optional per-call usage recorder. The evaluation harness installs a list here;
# runtime leaves it None so no overhead or import cycle is introduced.
usage_sink: list[dict] | None = None


def set_usage_sink(sink: list[dict] | None) -> None:
    global usage_sink
    usage_sink = sink


def complete_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """Chat completion expected to return a JSON object. Raises on unusable output."""
    settings = get_processing_settings()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = get_llm_client().chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=max_tokens,
            )
            break
        except RETRYABLE_ERRORS as exc:
            retryable = not isinstance(exc, APIStatusError) or exc.status_code in RETRYABLE_STATUS
            if not retryable or attempt == MAX_ATTEMPTS:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    if usage_sink is not None:
        usage = getattr(response, "usage", None)
        usage_sink.append(
            {
                "model": settings.llm_model,
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            }
        )
    content = (response.choices[0].message.content or "").strip()
    return _extract_json(content)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _extract_json(content: str) -> dict:
    """Tolerate markdown fences / preamble; find the outermost JSON object."""
    cleaned = _FENCE_RE.sub("", content).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object in LLM output: {content[:200]!r}")
    return json.loads(cleaned[start : end + 1])
