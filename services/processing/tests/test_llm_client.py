"""complete_json retries transient provider failures, and only those."""

from types import SimpleNamespace

import httpx
from app_core.clients import llm
from openai import APIConnectionError, APIStatusError


def _status_error(status: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return APIStatusError("provider returned an error", response=response, body=None)


def _client(calls: list, *, fail_times: int, status: int = 404, error: Exception | None = None):
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) <= fail_times:
                raise error or _status_error(status)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"total": 1}'))],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
            )

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


def _install(monkeypatch, calls, **kwargs):
    monkeypatch.setattr(llm, "get_llm_client", lambda: _client(calls, **kwargs))
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)


def test_a_transient_404_is_retried(monkeypatch):
    calls: list = []
    _install(monkeypatch, calls, fail_times=1)

    assert llm.complete_json("system", "user") == {"total": 1}
    assert len(calls) == 2


def test_a_connection_error_is_retried(monkeypatch):
    calls: list = []
    _install(monkeypatch, calls, fail_times=1, error=APIConnectionError(request=httpx.Request("POST", "https://x")))

    assert llm.complete_json("system", "user") == {"total": 1}
    assert len(calls) == 2


def test_it_gives_up_after_the_attempt_limit(monkeypatch):
    calls: list = []
    _install(monkeypatch, calls, fail_times=99)

    try:
        llm.complete_json("system", "user")
    except APIStatusError:
        pass
    else:  # pragma: no cover - the call must raise
        raise AssertionError("a persistent 404 must surface")

    assert len(calls) == llm.MAX_ATTEMPTS


def test_a_hard_error_is_not_retried(monkeypatch):
    calls: list = []
    _install(monkeypatch, calls, fail_times=99, status=400)

    try:
        llm.complete_json("system", "user")
    except APIStatusError:
        pass
    else:  # pragma: no cover - the call must raise
        raise AssertionError("a 400 must surface")

    assert len(calls) == 1


def test_usage_is_recorded_once_per_successful_call(monkeypatch):
    calls: list = []
    sink: list[dict] = []
    _install(monkeypatch, calls, fail_times=1)
    llm.set_usage_sink(sink)

    try:
        llm.complete_json("system", "user")
    finally:
        llm.set_usage_sink(None)

    assert len(sink) == 1
    assert sink[0]["total_tokens"] == 18
