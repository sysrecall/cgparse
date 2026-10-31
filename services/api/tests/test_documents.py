"""Read endpoints: list, filter, pagination, detail and per-page text."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app_core.models.document_page import DocumentPage
from app_core.models.processing_event import ProcessingEvent
from app_core.models.text_chunk import TextChunk
from app_core.models.validation_result import ValidationResult

URL = "/api/v1/documents"


def _make(document_factory, filename: str, **overrides):
    return document_factory(original_filename=filename, **overrides)


@pytest.mark.db
def test_list_is_empty_initially(client):
    response = client.get(URL)

    assert response.status_code == 200
    assert response.json() == {"total": 0, "page": 1, "size": 20, "items": []}


@pytest.mark.db
def test_list_orders_newest_first(client, document_factory):
    now = datetime.now(UTC)
    _make(document_factory, "old.csv", created_at=now - timedelta(hours=2))
    _make(document_factory, "middle.csv", created_at=now - timedelta(hours=1))
    _make(document_factory, "new.csv", created_at=now)

    response = client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["original_filename"] for item in body["items"]] == [
        "new.csv",
        "middle.csv",
        "old.csv",
    ]
    assert body["items"][0]["created_at"].startswith("20")


@pytest.mark.db
def test_list_paginates(client, document_factory):
    now = datetime.now(UTC)
    for index in range(3):
        _make(document_factory, f"doc-{index}.csv", created_at=now + timedelta(minutes=index))

    first = client.get(URL, params={"page": 1, "size": 2}).json()
    second = client.get(URL, params={"page": 2, "size": 2}).json()

    assert first["total"] == 3
    assert [item["original_filename"] for item in first["items"]] == ["doc-2.csv", "doc-1.csv"]
    assert first["page"] == 1 and first["size"] == 2
    assert [item["original_filename"] for item in second["items"]] == ["doc-0.csv"]


@pytest.mark.db
def test_list_filters_by_status(client, document_factory):
    _make(document_factory, "queued.csv", status="queued")
    _make(document_factory, "done.csv", status="validated")
    _make(document_factory, "review.csv", status="needs_review")

    body = client.get(URL, params={"status": "validated"}).json()

    assert body["total"] == 1
    assert body["items"][0]["original_filename"] == "done.csv"


def test_list_rejects_unknown_status(client):
    response = client.get(URL, params={"status": "banana"})
    assert response.status_code == 422


def test_list_rejects_oversized_page(client):
    assert client.get(URL, params={"size": 101}).status_code == 422
    assert client.get(URL, params={"size": 0}).status_code == 422
    assert client.get(URL, params={"page": 0}).status_code == 422


@pytest.mark.db
def test_detail_returns_404_for_unknown_document(client):
    response = client.get(f"{URL}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "document not found"


@pytest.mark.db
def test_detail_includes_extraction_line_items_and_history(
    client, db_session, document_factory, extraction_factory
):
    document = _make(document_factory, "invoice.csv", status="needs_review", page_count=1)
    extraction = extraction_factory(
        document,
        line_items=[
            {
                "description": "Widget",
                "quantity": 2,
                "unit_price": 50,
                "amount": 100,
                "confidence": 0.8,
                "provenance": {"source": "machine"},
            }
        ],
    )
    db_session.add(
        ValidationResult(
            extraction_id=extraction.id,
            rule_id="missing_field",
            severity="error",
            message="required field 'currency' is missing",
            field="currency",
        )
    )
    db_session.add(ProcessingEvent(document_id=document.id, stage="parse", status="ok"))
    db_session.commit()

    response = client.get(f"{URL}/{document.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(document.id)
    assert body["original_filename"] == "invoice.csv"
    assert body["status"] == "needs_review"
    assert body["extraction"]["id"] == str(extraction.id)
    assert body["extraction"]["fields"]["invoice_number"]["value"] == "INV-TEST-001"
    assert body["extraction"]["extraction_model"] == "test"

    assert len(body["line_items"]) == 1
    item = body["line_items"][0]
    assert item["description"] == "Widget"
    assert item["quantity"] == 2.0
    assert item["unit_price"] == 50.0
    assert item["amount"] == 100.0
    assert item["source"] == "machine"

    assert body["validation_results"] == [
        {
            "rule_id": "missing_field",
            "severity": "error",
            "message": "required field 'currency' is missing",
            "field": "currency",
        }
    ]
    assert body["history"][0]["stage"] == "parse"
    assert body["history"][0]["status"] == "ok"


@pytest.mark.db
def test_detail_without_extraction_returns_null_extraction(client, document_factory):
    document = _make(document_factory, "processing.csv", status="processing")

    body = client.get(f"{URL}/{document.id}").json()

    assert body["extraction"] is None
    assert body["line_items"] == []
    assert body["validation_results"] == []
    assert body["history"] == []


@pytest.mark.db
def test_pages_returns_404_for_unknown_document(client):
    response = client.get(f"{URL}/{uuid.uuid4()}/pages")
    assert response.status_code == 404


@pytest.mark.db
def test_pages_returns_page_text_and_chunks(client, db_session, document_factory):
    document = _make(document_factory, "scan.pdf", source_kind="pdf", mime_type="application/pdf")
    db_session.add_all(
        [
            DocumentPage(
                document_id=document.id,
                page_number=1,
                raw_text="first page",
                ocr_confidence=0.91,
            ),
            DocumentPage(document_id=document.id, page_number=2, raw_text="second page"),
            TextChunk(document_id=document.id, chunk_type="page", content="first page"),
            TextChunk(
                document_id=document.id,
                chunk_type="row",
                content="Total: 100.00",
                provenance_meta={"row": 1},
            ),
        ]
    )
    db_session.commit()

    body = client.get(f"{URL}/{document.id}/pages").json()

    assert body["document_id"] == str(document.id)
    assert body["page_count"] == 2
    assert [page["page_number"] for page in body["pages"]] == [1, 2]
    assert body["pages"][0]["raw_text"] == "first page"
    assert body["pages"][0]["ocr_confidence"] == 0.91
    assert body["pages"][1]["ocr_confidence"] is None
    assert {chunk["chunk_type"] for chunk in body["chunks"]} == {"page", "row"}
    row = next(chunk for chunk in body["chunks"] if chunk["chunk_type"] == "row")
    assert row["meta"] == {"row": 1}


@pytest.mark.db
def test_pages_without_pages_returns_empty_lists(client, document_factory):
    document = _make(document_factory, "empty.csv")

    body = client.get(f"{URL}/{document.id}/pages").json()

    assert body["page_count"] == 0
    assert body["pages"] == []
    assert body["chunks"] == []
