"""Pipeline stage tests: DB side effects, idempotency, human edits, failures."""

import uuid

import pytest
from app_core.models.document import Document
from app_core.models.document_page import DocumentPage
from app_core.models.extraction import Extraction
from app_core.models.line_item import LineItem
from app_core.models.processing_event import ProcessingEvent
from app_core.models.text_chunk import TextChunk
from app_core.models.validation_result import ValidationResult
from app_core.schemas.extraction import ExtractionOut
from app_core.testing import default_fields, field

from app.queues import pipeline


def extraction_out(**overrides) -> ExtractionOut:
    payload: dict = {
        "invoice_number": {"value": "INV-1", "confidence": 0.9},
        "invoice_date": {"value": "2026-10-01", "confidence": 0.9},
        "supplier_name": {"value": "Acme Supplies Ltd", "confidence": 0.9},
        "customer_name": {"value": "Northwind Traders", "confidence": 0.9},
        "subtotal": {"value": 100.0, "confidence": 0.9},
        "tax": {"value": 10.0, "confidence": 0.9},
        "total": {"value": 110.0, "confidence": 0.9},
        "currency": {"value": "USD", "confidence": 0.9},
        "document_confidence": 0.9,
        "line_items": [
            {
                "description": "Widget",
                "quantity": 2,
                "unit_price": 50,
                "amount": 100,
                "confidence": 0.9,
            }
        ],
    }
    payload.update(overrides)
    return ExtractionOut.model_validate(payload)


def add_chunks(session, document, contents=("Total: 110.00",)) -> None:
    for content in contents:
        session.add(TextChunk(document_id=document.id, chunk_type="row", content=content))
    session.commit()


def events(fresh, document_id) -> list[tuple[str, str]]:
    with fresh() as session:
        rows = (
            session.query(ProcessingEvent)
            .filter(ProcessingEvent.document_id == document_id)
            .order_by(ProcessingEvent.created_at, ProcessingEvent.stage)
            .all()
        )
        return [(row.stage, row.status) for row in rows]


# ── parse ────────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_parse_writes_chunks_and_events(pipeline_env, document_factory, fresh):
    document = document_factory(source_kind="csv", mime_type="text/csv")
    pipeline_env.storage[document.storage_key] = b"Invoice Number,Total\nINV-1,100.00\n"

    assert pipeline.parse_document.run(str(document.id)) == str(document.id)

    with fresh() as session:
        stored = session.get(Document, document.id)
        chunks = session.query(TextChunk).filter_by(document_id=document.id).all()
    assert stored.status == "queued"  # parse does not change status
    assert stored.page_count is None
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "row"
    assert chunks[0].content == "Invoice Number: INV-1; Total: 100.00"
    assert events(fresh, document.id) == [("parse", "started"), ("parse", "ok")]
    assert pipeline_env.published


@pytest.mark.db
def test_parse_writes_pages_for_paged_sources(pipeline_env, document_factory, fresh, monkeypatch):
    document = document_factory(source_kind="pdf", mime_type="application/pdf")
    pipeline_env.storage[document.storage_key] = b"%PDF-fake"
    monkeypatch.setattr(
        pipeline,
        "parse_any",
        lambda *args: (
            [
                {
                    "chunk_type": "page",
                    "page_number": 1,
                    "content": "page one",
                    "meta": {"ocr_confidence": 0.88},
                },
                {
                    "chunk_type": "page",
                    "page_number": 2,
                    "content": "page two",
                    "meta": {},
                },
            ],
            "fake",
        ),
    )

    pipeline.parse_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
        pages = (
            session.query(DocumentPage)
            .filter_by(document_id=document.id)
            .order_by(DocumentPage.page_number)
            .all()
        )
        chunks = session.query(TextChunk).filter_by(document_id=document.id).all()
    assert stored.page_count == 2
    assert [p.page_number for p in pages] == [1, 2]
    assert pages[0].ocr_confidence == 0.88
    assert pages[1].ocr_confidence is None
    assert len(chunks) == 2


@pytest.mark.db
def test_parse_is_idempotent(pipeline_env, document_factory, fresh):
    document = document_factory()
    pipeline_env.storage[document.storage_key] = b"a,b\n1,2\n"

    pipeline.parse_document.run(str(document.id))
    pipeline.parse_document.run(str(document.id))

    with fresh() as session:
        chunks = session.query(TextChunk).filter_by(document_id=document.id).all()
    assert len(chunks) == 1
    assert events(fresh, document.id).count(("parse", "ok")) == 2


@pytest.mark.db
def test_parse_failure_marks_document_failed(pipeline_env, document_factory, fresh):
    document = document_factory()

    with pytest.raises(KeyError):
        pipeline.parse_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "failed"
    assert stored.failure_reason.startswith("parse: KeyError")
    assert ("parse", "failed") in events(fresh, document.id)


@pytest.mark.db
def test_parse_missing_document_is_a_noop(pipeline_env):
    document_id = str(uuid.uuid4())
    assert pipeline.parse_document.run(document_id) == document_id


# ── extract ──────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_extract_writes_extraction_and_line_items(
    pipeline_env, document_factory, db_session, fresh
):
    document = document_factory()
    add_chunks(db_session, document)
    pipeline_env.calls.extraction = extraction_out()

    pipeline.extract_document.run(str(document.id))

    with fresh() as session:
        extraction = session.query(Extraction).filter_by(document_id=document.id).one()
        items = (
            session.query(LineItem)
            .filter_by(extraction_id=extraction.id)
            .order_by(LineItem.position)
            .all()
        )
    assert extraction.extraction_model == "heuristics"  # no LLM key in tests
    assert extraction.document_confidence == pytest.approx(0.9)
    assert extraction.fields["total"]["value"] == 110.0
    assert len(items) == 1
    assert items[0].position == 1
    assert items[0].amount == 100
    assert items[0].provenance == {"source": "machine"}


@pytest.mark.db
def test_extract_preserves_human_fields_and_line_items(
    pipeline_env, document_factory, db_session, extraction_factory, fresh
):
    document = document_factory()
    add_chunks(db_session, document)
    extraction_factory(
        document,
        fields={**default_fields(), "supplier_name": field("Human Co", 1.0, "human")},
        line_items=[
            {
                "description": "Human line",
                "quantity": 1,
                "unit_price": 100,
                "amount": 100,
                "provenance": {"source": "human"},
            }
        ],
    )
    pipeline_env.calls.extraction = extraction_out(
        supplier_name={"value": "Machine Co", "confidence": 0.9}
    )

    pipeline.extract_document.run(str(document.id))

    with fresh() as session:
        extractions = session.query(Extraction).filter_by(document_id=document.id).all()
        items = session.query(LineItem).filter_by(extraction_id=extractions[0].id).all()
    assert len(extractions) == 1
    assert extractions[0].fields["supplier_name"] == field("Human Co", 1.0, "human")
    assert len(items) == 1
    assert items[0].description == "Human line"
    assert items[0].provenance == {"source": "human"}


@pytest.mark.db
def test_extract_replaces_machine_line_items(
    pipeline_env, document_factory, db_session, extraction_factory, fresh
):
    document = document_factory()
    add_chunks(db_session, document)
    extraction_factory(
        document,
        line_items=[{"description": "Old machine line", "amount": 55}],
    )
    pipeline_env.calls.extraction = extraction_out()

    pipeline.extract_document.run(str(document.id))

    with fresh() as session:
        extraction = session.query(Extraction).filter_by(document_id=document.id).one()
        items = session.query(LineItem).filter_by(extraction_id=extraction.id).all()
    assert [item.description for item in items] == ["Widget"]
    assert items[0].provenance == {"source": "machine"}


@pytest.mark.db
def test_extract_without_chunks_fails(pipeline_env, document_factory, fresh):
    document = document_factory()

    with pytest.raises(ValueError, match="no text chunks"):
        pipeline.extract_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "failed"
    assert stored.failure_reason.startswith("extract: ValueError")


# ── validate ─────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_validate_marks_clean_document_validated(
    pipeline_env, document_factory, extraction_factory, fresh
):
    document = document_factory()
    extraction_factory(
        document,
        line_items=[{"description": "Widget", "amount": 100}],
    )

    pipeline.validate_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
        extraction = session.query(Extraction).filter_by(document_id=document.id).one()
        findings = session.query(ValidationResult).filter_by(extraction_id=extraction.id).all()
    assert stored.status == "validated"
    assert findings == []


@pytest.mark.db
def test_validate_routes_bad_documents_to_review(
    pipeline_env, document_factory, extraction_factory, fresh
):
    document = document_factory()
    extraction_factory(
        document,
        fields={**default_fields(), "currency": field(None), "total": field(120.0)},
        line_items=[{"description": "Widget", "amount": 90}],
    )

    pipeline.validate_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
        extraction = session.query(Extraction).filter_by(document_id=document.id).one()
        findings = session.query(ValidationResult).filter_by(extraction_id=extraction.id).all()
    assert stored.status == "needs_review"
    assert {f.rule_id for f in findings} == {
        "missing_field",
        "line_items_sum",
        "subtotal_tax_total",
    }


@pytest.mark.db
def test_validate_replaces_prior_findings(
    pipeline_env, document_factory, extraction_factory, fresh
):
    document = document_factory()
    extraction_factory(
        document,
        fields={**default_fields(), "currency": field(None)},
    )

    pipeline.validate_document.run(str(document.id))
    pipeline.validate_document.run(str(document.id))

    with fresh() as session:
        extraction = session.query(Extraction).filter_by(document_id=document.id).one()
        findings = session.query(ValidationResult).filter_by(extraction_id=extraction.id).all()
    assert len(findings) == 1
    assert findings[0].rule_id == "missing_field"


@pytest.mark.db
def test_validate_without_extraction_fails(pipeline_env, document_factory, fresh):
    document = document_factory()

    with pytest.raises(ValueError, match="no extraction"):
        pipeline.validate_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "failed"


# ── index ────────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_index_requires_chunks(pipeline_env, document_factory, db_session, fresh):
    document = document_factory()
    add_chunks(db_session, document)

    pipeline.index_document.run(str(document.id))

    assert ("index", "ok") in events(fresh, document.id)


@pytest.mark.db
def test_index_without_chunks_fails(pipeline_env, document_factory, fresh):
    document = document_factory()

    with pytest.raises(ValueError, match="no chunks"):
        pipeline.index_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "failed"
    assert stored.failure_reason.startswith("index: ValueError")


# ── orchestration / failures ─────────────────────────────────────────────────


@pytest.mark.db
def test_downstream_stages_noop_after_failure(
    pipeline_env, document_factory, db_session, fresh
):
    document = document_factory(status="failed")
    add_chunks(db_session, document)

    pipeline.extract_document.run(str(document.id))
    pipeline.validate_document.run(str(document.id))
    pipeline.index_document.run(str(document.id))

    with fresh() as session:
        assert session.query(Extraction).filter_by(document_id=document.id).count() == 0
        assert session.query(ProcessingEvent).filter_by(document_id=document.id).count() == 0


@pytest.mark.db
def test_route_dispatches_the_full_chain(pipeline_env, document_factory, monkeypatch, fresh):
    dispatched: list[tuple] = []

    class FakeChain:
        def __init__(self, *stages):
            self.stages = stages

        def apply_async(self):
            dispatched.append(self.stages)

    monkeypatch.setattr(pipeline, "chain", FakeChain)
    document = document_factory()

    pipeline.route_document.run(str(document.id))

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "processing"
    assert len(dispatched) == 1
    assert len(dispatched[0]) == 4
    assert ("route", "ok") in events(fresh, document.id)


@pytest.mark.db
def test_route_can_resume_from_extract(pipeline_env, document_factory, monkeypatch):
    dispatched: list[tuple] = []

    class FakeChain:
        def __init__(self, *stages):
            self.stages = stages

        def apply_async(self):
            dispatched.append(self.stages)

    monkeypatch.setattr(pipeline, "chain", FakeChain)
    document = document_factory()

    pipeline.route_document.run(str(document.id), from_stage="extract")

    assert len(dispatched[0]) == 3


def test_route_rejects_unknown_stage(pipeline_env):
    with pytest.raises(ValueError, match="invalid from_stage"):
        pipeline.route_document.run(str(uuid.uuid4()), from_stage="validate")


@pytest.mark.db
def test_route_missing_document_raises(pipeline_env):
    with pytest.raises(ValueError, match="not found"):
        pipeline.route_document.run(str(uuid.uuid4()))


@pytest.mark.db
def test_task_on_failure_guard_records_reason(pipeline_env, document_factory, fresh):
    document = document_factory()

    pipeline.parse_document.on_failure(
        ValueError("worker died"), "task-1", (str(document.id),), {}, None
    )

    with fresh() as session:
        stored = session.get(Document, document.id)
    assert stored.status == "failed"
    assert stored.failure_reason == "parse: ValueError: worker died"
