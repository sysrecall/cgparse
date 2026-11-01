"""Settings: the OCR model is configurable, with PaddleOCR-VL as the default."""

from app_core.settings import EmbeddingSettings, ProcessingSettings


def test_processing_settings_read_the_openparser_model(monkeypatch):
    monkeypatch.setenv("PROC_OPENPARSER_MODEL", "mistral-ocr-4")

    assert ProcessingSettings().openparser_model == "mistral-ocr-4"


def test_processing_settings_default_to_paddleocr(monkeypatch):
    monkeypatch.delenv("PROC_OPENPARSER_MODEL", raising=False)

    assert ProcessingSettings().openparser_model == "paddleocr-vl-1.6"


def test_embedding_settings_keep_their_own_namespace(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "some/other-embedder")
    monkeypatch.setenv("EMBED_DIMENSIONS", "1024")

    settings = EmbeddingSettings()

    assert settings.model == "some/other-embedder"
    assert settings.dimensions == 1024
