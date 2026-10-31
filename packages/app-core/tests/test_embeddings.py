"""Embedding client: batching, dimension checks, retries, error surfacing."""

from types import SimpleNamespace

import httpx
import pytest

from app_core.clients import embeddings


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "model": "test-embed",
        "dimensions": 4,
        "batch_size": 2,
        "api_key": "test-key",
        "base_url": "https://embed.test/v1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://embed.test/v1", transport=httpx.MockTransport(handler))


def _reply(vectors, status=200, start_index=0):
    return httpx.Response(
        status,
        json={
            "data": [
                {"index": start_index + offset, "embedding": vector}
                for offset, vector in enumerate(vectors)
            ]
        },
    )


def test_embed_texts_batches_and_keeps_input_order(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings(batch_size=2))
    batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        batches.append(payload["input"])
        assert payload["input_type"] == "passage"
        assert payload["dimensions"] == 4
        # Return vectors in reverse order to prove the client re-sorts by index.
        vectors = [[float(len(batches)), 0.0, 0.0, 0.0] for _ in payload["input"]]
        return _reply(list(reversed(vectors)), start_index=0)

    with _client(handler) as client:
        result = embeddings.embed_texts(["a", "b", "c"], input_type="passage", client=client)

    assert len(result) == 3
    assert batches == [["a", "b"], ["c"]]


def test_embed_texts_rejects_wrong_dimensions(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings(dimensions=4))

    def handler(request: httpx.Request) -> httpx.Response:
        return _reply([[0.0, 0.0, 0.0]])

    with _client(handler) as client, pytest.raises(embeddings.EmbeddingError, match="expected 4"):
        embeddings.embed_texts(["a"], input_type="passage", client=client)


def test_embed_texts_retries_server_errors(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings())
    monkeypatch.setattr(embeddings.time, "sleep", lambda _seconds: None)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="overloaded")
        return _reply([[1.0, 0.0, 0.0, 0.0]])

    with _client(handler) as client:
        result = embeddings.embed_texts(["a"], input_type="query", client=client)

    assert attempts["count"] == 3
    assert result == [[1.0, 0.0, 0.0, 0.0]]


def test_embed_texts_surfaces_client_errors_without_retrying(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings())
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, text="bad input")

    with _client(handler) as client, pytest.raises(embeddings.EmbeddingError, match="HTTP 400"):
        embeddings.embed_texts(["a"], input_type="passage", client=client)

    assert attempts["count"] == 1


def test_embed_texts_without_a_key_fails_fast(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings(api_key=""))

    with pytest.raises(embeddings.EmbeddingError, match="API key"):
        embeddings.embed_texts(["a"], input_type="passage")


def test_embed_texts_blank_input_yields_no_request(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings())
    assert embeddings.embed_texts([], input_type="passage") == []


def test_embed_query_uses_the_query_input_type(monkeypatch):
    monkeypatch.setattr(embeddings, "get_embedding_settings", lambda: _settings())
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(__import__("json").loads(request.content))
        return _reply([[0.5, 0.5, 0.5, 0.5]])

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    captured: dict = {}

    def make_client(**kwargs):
        captured.update(kwargs)
        return real_client(base_url="https://embed.test/v1", transport=transport)

    monkeypatch.setattr(embeddings.httpx, "Client", make_client)

    assert embeddings.embed_query("who owes us money") == [0.5, 0.5, 0.5, 0.5]
    assert seen["input_type"] == "query"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
