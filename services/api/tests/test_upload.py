"""Upload endpoint: per-file isolation, dedupe, limits, enqueue-after-commit."""

import hashlib
import uuid
from types import SimpleNamespace

import pytest
from app_core.models.document import Document
from sqlalchemy import select

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
def test_duplicate_mid_batch_keeps_the_other_files(client, recorded, db_session):
    other = b"Invoice Number,Total\nINV-2,200.00\n"

    response = upload(
        client,
        [
            ("files", ("first.csv", CSV, "text/csv")),
            ("files", ("copy.csv", CSV, "text/csv")),
            ("files", ("second.csv", other, "text/csv")),
        ],
    )

    assert response.status_code == 202
    items = response.json()["items"]
    assert items[0]["error"] is None
    assert "duplicate file" in items[1]["error"]
    assert items[2]["error"] is None

    accepted = {uuid.UUID(item["document_id"]) for item in items if item["document_id"]}
    assert len(accepted) == 2
    # Both accepted files really survived the duplicate's rollback.
    assert set(db_session.scalars(select(Document.id)).all()) == accepted
    assert {args[0] for _, args, _ in recorded.enqueued} == accepted
    # The duplicate was rejected before it reached object storage.
    assert len(recorded.stored) == 2
    assert recorded.deleted == []


@pytest.mark.db
def test_storage_failure_mid_batch_keeps_the_other_files(client, recorded, db_session, monkeypatch):
    working_upload = ingest.upload_stream

    def flaky_upload(key, stream, content_type):
        if "second.csv" in key:
            raise RuntimeError("storage exploded")
        working_upload(key, stream, content_type)

    monkeypatch.setattr(ingest, "upload_stream", flaky_upload)
    other = b"Invoice Number,Total\nINV-3,300.00\n"

    response = upload(
        client,
        [
            ("files", ("first.csv", CSV, "text/csv")),
            ("files", ("second.csv", other, "text/csv")),
            ("files", ("third.csv", b"Invoice Number,Total\nINV-4,400.00\n", "text/csv")),
        ],
    )

    items = response.json()["items"]
    assert items[0]["error"] is None
    assert "RuntimeError: storage exploded" in items[1]["error"]
    assert items[2]["error"] is None

    accepted = {uuid.UUID(item["document_id"]) for item in items if item["document_id"]}
    assert len(accepted) == 2
    assert set(db_session.scalars(select(Document.id)).all()) == accepted
    assert len(recorded.enqueued) == 2
    assert len(recorded.deleted) == 1  # the half-uploaded object was cleaned up


@pytest.mark.db
def test_lost_duplicate_race_is_reported_and_the_object_is_deleted(
    client, recorded, db_session_factory, monkeypatch
):
    """Another request commits the same bytes between our lookup and our insert."""

    def racing_upload(key, stream, content_type):
        recorded.stored[key] = {"content_type": content_type, "data": stream.read()}
        with db_session_factory() as other:
            other.add(
                Document(
                    id=uuid.uuid4(),
                    original_filename="winner.csv",
                    checksum_sha256=hashlib.sha256(CSV).hexdigest(),
                    mime_type="text/csv",
                    source_kind="csv",
                    storage_key="documents/winner/original/winner.csv",
                    size_bytes=len(CSV),
                    status="queued",
                )
            )
            other.commit()

    monkeypatch.setattr(ingest, "upload_stream", racing_upload)

    response = upload(client, [("files", ("race.csv", CSV, "text/csv"))])

    item = response.json()["items"][0]
    assert "duplicate file" in item["error"]
    assert item["document_id"] is None
    assert len(recorded.deleted) == 1
    assert recorded.deleted[0] in recorded.stored
    assert recorded.enqueued == []


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
