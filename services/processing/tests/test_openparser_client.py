"""The OCR model comes from PROC_OPENPARSER_MODEL, not a hard-coded constant."""

from types import SimpleNamespace

import openparser
import pytest
from app_core.clients import openparser as ocr


def _install(monkeypatch, captured: dict) -> None:
    """Replace the SDK client so the request and file reach a dict."""

    def sync(request, *, file):
        captured["request"] = request
        captured["suffix"] = file.suffix
        return SimpleNamespace(
            elements=[
                SimpleNamespace(
                    kind="text",
                    text="INVOICE 1",
                    confidence=SimpleNamespace(score=0.9),
                    locations=[],
                )
            ]
        )

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key

        @property
        def parse(self):
            return SimpleNamespace(sync=sync)

    monkeypatch.setattr(openparser, "OpenParserClient", FakeClient)


def _settings(**overrides):
    base = {"openparser_api_key": "test-key", "openparser_model": "paddleocr-vl-1.6"}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_the_configured_model_is_sent(monkeypatch):
    captured: dict = {}
    _install(monkeypatch, captured)
    monkeypatch.setattr(
        ocr, "get_processing_settings", lambda: _settings(openparser_model="mistral-ocr-4")
    )

    result = ocr.parse_document(b"image-bytes", "scan.png")

    assert captured["request"] == {"ocr_model": "mistral-ocr-4"}
    assert captured["api_key"] == "test-key"
    assert captured["suffix"] == ".png"
    assert result["pages"][0]["text"] == "INVOICE 1"


def test_blank_model_falls_back_to_the_default(monkeypatch):
    captured: dict = {}
    _install(monkeypatch, captured)
    monkeypatch.setattr(ocr, "get_processing_settings", lambda: _settings(openparser_model="  "))

    ocr.parse_document(b"image-bytes", "scan.jpg")

    assert captured["request"] == {"ocr_model": ocr.DEFAULT_OCR_MODEL}


def test_missing_api_key_never_reaches_the_provider(monkeypatch):
    captured: dict = {}
    _install(monkeypatch, captured)
    monkeypatch.setattr(ocr, "get_processing_settings", lambda: _settings(openparser_api_key=""))

    with pytest.raises(ocr.OpenParserError, match="OPENPARSER_API_KEY"):
        ocr.parse_document(b"image-bytes", "scan.png")

    assert captured == {}


def test_unsupported_suffix_is_rejected_before_upload(monkeypatch):
    captured: dict = {}
    _install(monkeypatch, captured)
    monkeypatch.setattr(ocr, "get_processing_settings", lambda: _settings())

    with pytest.raises(ocr.OpenParserError, match="PDF/PNG/JPEG"):
        ocr.parse_document(b"image-bytes", "scan.tiff")

    assert captured == {}
