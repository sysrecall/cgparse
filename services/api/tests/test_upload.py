"""Upload endpoint: per-file isolation, dedupe, limits, enqueue-after-commit."""

import hashlib
import uuid
from types import SimpleNamespace

import pytest
from app_core.models.document import Document

from app.services import ingest

CSV = b"Invoice Number,Total\nINV-1,100.00\n"
PNG = __import__("base64").b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
EXE = b"MZ" + b"\x00" * 120

URL = "/api/v1/documents"


def upload(client, files):
    return client.post(URL, files=files)


@pytest.mark.db
def test_upload_accepts_csv_and_enqueues_after_commit(client, db_session, recorded):
    response = upload(client, [("files", ("invoice.csv", CSV, "text/csv"))])

    assert response.status_code == 202
    item = response.json()["items"][0]
    assert item["error"] is None
    assert item["status"] == "queued"

    document = db_session.get(Document, uuid.UUID(item["document_id"]))
    assert document.original_filename == "invoice.csv"
    assert document.source_kind == "csv"
    assert document.size_bytes == len(CSV)
    assert document.checksum_sha256 == hashlib.sha256(CSV).hexdigest()
    assert document.storage_key == f"documents/{document.id}/original/invoice.csv"

    stored = recorded.stored[document.storage_key]
    assert stored["data"] == CSV
    assert stored["content_type"] == "text/csv"
    assert recorded.enqueued == [("route", (document.id,), {})]


@pytest.mark.db
def test_upload_isolates_a_bad_file_in_a_batch(client, recorded):
    response = upload(
        client,
        [
            ("files", ("invoice.csv", CSV, "text/csv")),
            ("files", ("scan.png", PNG, "image/png")),
            ("files", ("setup.exe", EXE, "application/octet-stream")),
        ],
    )

    assert response.status_code == 202
    items = response.json()["items"]
    assert len(items) == 3
    assert sum(1 for item in items if item["document_id"]) == 2
    assert "unsupported file type" in next(item["error"] for item in items if item["error"])
    assert len(recorded.enqueued) == 2


@pytest.mark.db
def test_upload_rejects_empty_files(client, recorded):
    response = upload(client, [("files", ("empty.csv", b"", "text/csv"))])

    assert response.status_code == 202
    assert response.json()["items"][0]["error"] == "empty file"
    assert recorded.stored == {}
    assert recorded.enqueued == []


@pytest.mark.db
def test_upload_requires_at_least_one_file(client):
    response = client.post(URL)
    assert response.status_code == 422


@pytest.mark.db
def test_duplicate_bytes_are_rejected_on_the_second_upload(client, recorded):
    first = upload(client, [("files", ("invoice.csv", CSV, "text/csv"))])
    assert first.json()["items"][0]["error"] is None

    second = upload(client, [("files", ("copy.csv", CSV, "text/csv"))])

    assert second.status_code == 202
    error = second.json()["items"][0]["error"]
    assert "duplicate file" in error
    assert len(recorded.enqueued) == 1


@pytest.mark.db
def test_upload_size_limit_is_enforced(client, monkeypatch):
    monkeypatch.setattr(
        ingest,
        "get_api_settings",
        lambda: SimpleNamespace(max_upload_mb=0),
    )

    response = upload(client, [("files", ("invoice.csv", CSV, "text/csv"))])

    assert response.status_code == 202
    assert "exceeds 0 MB limit" in response.json()["items"][0]["error"]
