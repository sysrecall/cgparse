"""Corrections + reprocess: coercion, human provenance, re-validation, enqueue."""

import uuid

import pytest
from app_core.models.document import Document
from app_core.models.extraction import Extraction
from app_core.models.line_item import LineItem
from app_core.models.validation_result import ValidationResult

URL = "/api/v1/documents"


def _patch(client, document_id, body):
    return client.patch(f"{URL}/{document_id}/corrections", json=body)


@pytest.mark.db
def test_correction_returns_404_for_unknown_document(client):
    response = _patch(client, uuid.uuid4(), {"fields": {"currency": "USD"}})
    assert response.status_code == 404


@pytest.mark.db
def test_correction_returns_409_without_an_extraction(client, document_factory):
    document = document_factory()

    response = _patch(client, document.id, {"fields": {"currency": "USD"}})

    assert response.status_code == 409
    assert response.json()["detail"] == "document has no extraction to correct"


@pytest.mark.db
def test_correction_rejects_an_empty_body(client, document_factory, extraction_factory):
    document = document_factory()
    extraction_factory(document)

    response = _patch(client, document.id, {})

    assert response.status_code == 422
    assert response.json()["detail"] == "nothing to correct"


@pytest.mark.db
def test_correction_rejects_unknown_fields(client, document_factory, extraction_factory):
    document = document_factory()
    extraction_factory(document)

    response = _patch(client, document.id, {"fields": {"not_a_field": "x"}})

    assert response.status_code == 422
    assert "unknown fields" in response.json()["detail"]


@pytest.mark.db
def test_correction_rejects_bad_money_and_dates(client, document_factory, extraction_factory):
    document = document_factory()
    extraction_factory(document)

    bad_money = _patch(client, document.id, {"fields": {"total": "not-money"}})
    bad_date = _patch(client, document.id, {"fields": {"invoice_date": "31/02/2026"}})

    assert bad_money.status_code == 422
    assert "not a number" in bad_money.json()["detail"]
    assert bad_date.status_code == 422
    assert "not a valid date" in bad_date.json()["detail"]


@pytest.mark.db
def test_header_correction_is_partial_and_stamped_human(
    client, db_session, fresh, document_factory, extraction_factory, recorded
):
    document = document_factory(status="needs_review")
    extraction = extraction_factory(document)
    db_session.add(
        ValidationResult(
            extraction_id=extraction.id,
            rule_id="missing_field",
            severity="error",
            message="required field 'currency' is missing",
            field="currency",
        )
    )
    db_session.commit()

    response = _patch(
        client,
        document.id,
        {"fields": {"currency": "eur", "total": "4,950.00", "invoice_date": "October 5, 2026"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document.id)
    assert body["status"] == "processing"
    assert body["corrected_fields"] == ["currency", "total", "invoice_date"]
    assert body["line_items_replaced"] is False
    assert body["findings_cleared"] == 1
    assert body["revalidation_queued"] is True
    assert recorded.enqueued == [("validate", (document.id,), {})]

    with fresh() as session:
        stored_document = session.get(Document, document.id)
        stored = session.query(Extraction).filter_by(document_id=document.id).one()

    assert stored_document.status == "processing"
    assert stored.fields["currency"] == {"value": "eur", "confidence": 1.0, "source": "human"}
    assert stored.fields["total"] == {"value": 4950.0, "confidence": 1.0, "source": "human"}
    assert stored.fields["invoice_date"] == {
        "value": "2026-10-05",
        "confidence": 1.0,
        "source": "human",
    }
    # untouched fields keep their machine values
    assert stored.fields["supplier_name"]["value"] == "Acme Supplies Ltd"
    assert stored.fields["supplier_name"]["source"] == "heuristic"
    # 5 machine fields @0.9 + 3 human fields @1.0, averaged over 8 present values
    assert stored.document_confidence == pytest.approx(0.9375)


@pytest.mark.db
def test_line_item_correction_replaces_the_whole_set(
    client, fresh, document_factory, extraction_factory
):
    document = document_factory()
    extraction = extraction_factory(
        document,
        line_items=[
            {"description": "Old A", "amount": 40},
            {"description": "Old B", "amount": 60},
        ],
    )

    response = _patch(
        client,
        document.id,
        {
            "line_items": [
                {
                    "description": "Corrected",
                    "quantity": 2,
                    "unit_price": 12.5,
                    "amount": 25.0,
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["line_items_replaced"] is True
    assert body["corrected_fields"] == []

    with fresh() as session:
        items = (
            session.query(LineItem)
            .filter_by(extraction_id=extraction.id)
            .order_by(LineItem.position)
            .all()
        )
    assert len(items) == 1
    assert items[0].position == 1
    assert items[0].description == "Corrected"
    assert float(items[0].quantity) == 2.0
    assert float(items[0].unit_price) == 12.5
    assert float(items[0].amount) == 25.0
    assert items[0].confidence == 1.0
    assert items[0].provenance == {"source": "human"}


@pytest.mark.db
def test_correction_clears_failure_reason(client, fresh, document_factory, extraction_factory):
    document = document_factory(status="failed", failure_reason="extract: boom")
    extraction_factory(document)

    response = _patch(client, document.id, {"fields": {"currency": "USD"}})

    assert response.status_code == 200
    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "processing"
    assert stored.failure_reason is None


@pytest.mark.db
def test_reprocess_returns_404_for_unknown_document(client):
    response = client.post(f"{URL}/{uuid.uuid4()}/reprocess")
    assert response.status_code == 404


@pytest.mark.db
def test_reprocess_defaults_to_parse(client, fresh, document_factory, recorded):
    document = document_factory(status="failed", failure_reason="parse: boom")

    response = client.post(f"{URL}/{document.id}/reprocess")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "document_id": str(document.id),
        "status": "queued",
        "from_stage": "parse",
    }
    assert recorded.enqueued == [("route", (document.id,), {"from_stage": "parse"})]

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "queued"
    assert stored.failure_reason is None


@pytest.mark.db
def test_reprocess_can_start_from_extract(client, document_factory, recorded):
    document = document_factory(status="needs_review")

    response = client.post(f"{URL}/{document.id}/reprocess", params={"from": "extract"})

    assert response.status_code == 200
    assert response.json()["from_stage"] == "extract"
    assert recorded.enqueued == [("route", (document.id,), {"from_stage": "extract"})]


@pytest.mark.db
def test_reprocess_rejects_an_unknown_stage(client, document_factory):
    document = document_factory()

    response = client.post(f"{URL}/{document.id}/reprocess", params={"from": "validate"})

    assert response.status_code == 422
