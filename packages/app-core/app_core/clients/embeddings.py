"""Embedding client (OpenAI-compatible; NVIDIA NIM by default).

The model is asymmetric: passages and queries must be embedded with different
`input_type` values, otherwise retrieval quality collapses silently. The
provider returns unit-length vectors, so cosine distance is a plain dot product.

`dimensions` is sent explicitly so vectors fit the existing
`text_chunks.embedding vector(1536)` column — the default model is natively
2048-wide, and the truncation was measured to preserve ranking.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Literal

import httpx

from app_core.settings import get_embedding_settings

InputType = Literal["query", "passage"]

MAX_ATTEMPTS = 3


class EmbeddingError(RuntimeError):
    """The provider refused the request or returned an unusable payload."""


def _post_batch(
    client: httpx.Client,
    model: str,
    dimensions: int,
    batch: list[str],
    input_type: InputType,
) -> list[list[float]]:
    payload = {
        "model": model,
        "input": batch,
        "input_type": input_type,
        "dimensions": dimensions,
        # A single over-long chunk must not fail an entire document.
        "truncate": "END",
    }

    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.post("/embeddings", json=payload)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code >= 500 or response.status_code == 429:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            elif response.status_code >= 400:
                raise EmbeddingError(
                    f"embedding request rejected: HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
            else:
                return _vectors(response.json(), dimensions, model, len(batch))
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(2**attempt)

    raise EmbeddingError(f"embedding request failed after {MAX_ATTEMPTS} attempts: {last_error}")


def _vectors(body: dict, dimensions: int, model: str, expected: int) -> list[list[float]]:
    rows = body.get("data") or []
    if len(rows) != expected:
        raise EmbeddingError(f"expected {expected} embeddings, got {len(rows)}")

    ordered = sorted(rows, key=lambda row: row.get("index", 0))
    vectors = [row.get("embedding") or [] for row in ordered]
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError(
                f"model {model!r} returned {len(vector)} dimensions, expected {dimensions}"
            )
    return vectors


def embed_texts(
    texts: Sequence[str],
    *,
    input_type: InputType,
    client: httpx.Client | None = None,
) -> list[list[float]]:
    """Embed every text, batching requests. Returns one vector per input."""
    if not texts:
        return []

    settings = get_embedding_settings()
    if not settings.api_key:
        raise EmbeddingError("no embedding API key: set EMBED_API_KEY or PROC_LLM_API_KEY")

    # The provider rejects blank input, and blank chunks are common (empty pages).
    prepared = [text if text and text.strip() else " " for text in texts]
    owns_client = client is None
    http_client = client or httpx.Client(
        base_url=settings.base_url.rstrip("/"),
        timeout=httpx.Timeout(90.0),
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )
    try:
        vectors: list[list[float]] = []
        size = max(1, settings.batch_size)
        for start in range(0, len(prepared), size):
            vectors.extend(
                _post_batch(
                    http_client,
                    settings.model,
                    settings.dimensions,
                    prepared[start : start + size],
                    input_type,
                )
            )
        return vectors
    finally:
        if owns_client:
            http_client.close()


def embed_passages(texts: Sequence[str]) -> list[list[float]]:
    return embed_texts(texts, input_type="passage")


def embed_query(text: str) -> list[float]:
    return embed_texts([text], input_type="query")[0]
