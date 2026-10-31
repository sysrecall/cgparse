"""The pipeline: route → parse → extract → validate → index.

- Each stage is its own Celery task (independently retryable, per architecture §4).
- Tasks pass document_id along; every stage no-ops if the document already failed.
- Any unhandled exception marks the document failed (with reason) and re-raises.
- Progress is published to Redis pub/sub after every stage (api SSE subscribes).

Data flow:
  parse    -> writes document_pages (paged sources) + text_chunks (all sources)
  extract  -> reads text back from DB, runs heuristics + LLM, writes extraction
  validate -> six rules, writes validation_results, sets final status
  index    -> embeds chunks into text_chunks.embedding for semantic search
"""

import uuid

from app_core.clients.embeddings import embed_passages
from app_core.clients.storage import download
from app_core.db import session_scope
from app_core.models.document import Document
from app_core.models.document_page import DocumentPage
from app_core.models.enums import DocumentStatus
from app_core.models.extraction import Extraction
from app_core.models.line_item import LineItem
from app_core.models.processing_event import ProcessingEvent
from app_core.models.text_chunk import TextChunk
from app_core.models.validation_result import ValidationResult
from app_core.settings import get_embedding_settings, get_processing_settings
from celery import chain
from sqlalchemy import select

from app.celery_app import celery_app
from app.events import publish
from app.llm.extract import extract as run_extraction
from app.queues.parsers import parse_any
from app.validation.rules import run_all


def _log_event(session, document_id: uuid.UUID, stage: str, status: str, detail: str | None = None) -> None:
    session.add(ProcessingEvent(document_id=document_id, stage=stage, status=status, detail=detail))
    publish({"document_id": str(document_id), "stage": stage, "status": status})


def _fail(session, document_id: uuid.UUID, stage: str, exc: Exception) -> None:
    doc = session.get(Document, document_id)
    if doc:
        doc.status = DocumentStatus.FAILED.value
        doc.failure_reason = f"{stage}: {type(exc).__name__}: {exc}"[:500]
    _log_event(session, document_id, stage, "failed", str(exc)[:500])


def _get_document(session, document_id: uuid.UUID) -> Document | None:
    doc = session.get(Document, document_id)
    if doc is None or doc.status == DocumentStatus.FAILED.value:
        return None  # missing or upstream-failed -> downstream no-ops
    return doc


class _PipelineTask(celery_app.Task):
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        """Last-resort guard when a stage dies before its own handler runs."""
        document_id = args[0] if args else None
        if not document_id:
            return
        stage = (self.name or "pipeline").split(".")[-1].replace("_document", "")
        try:
            with session_scope() as session:
                _fail(session, uuid.UUID(str(document_id)), stage, exc)
        except Exception:  # noqa: BLE001, S110 — DB itself may be unreachable; nothing left to do
            pass


@celery_app.task(bind=True, base=_PipelineTask, name="processing.route_document", queue="ocr")
def route_document(self, document_id: str, from_stage: str = "parse") -> str:
    doc_id = uuid.UUID(document_id)
    if from_stage not in ("parse", "extract"):
        raise ValueError(f"invalid from_stage={from_stage!r}; expected 'parse' or 'extract'")
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"document {doc_id} not found")
        doc.status = DocumentStatus.PROCESSING.value
        doc.failure_reason = None  # a re-run clears the previous failure
        _log_event(session, doc_id, "route", "ok", f"source_kind={doc.source_kind} from={from_stage}")
    # The api only ever sends this one task (services stay decoupled) —
    # route owns dispatching the rest of the chain, from the requested stage.
    if from_stage == "extract":
        stages = (extract_document.s(document_id), validate_document.s(), index_document.s())
    else:
        stages = (
            parse_document.s(document_id),
            extract_document.s(),
            validate_document.s(),
            index_document.s(),
        )
    chain(*stages).apply_async()
    return document_id


@celery_app.task(bind=True, base=_PipelineTask, name="processing.parse_document", queue="ocr")
def parse_document(self, document_id: str) -> str:
    doc_id = uuid.UUID(document_id)
    try:
        with session_scope() as session:
            doc = _get_document(session, doc_id)
            if doc is None:
                return document_id
            _log_event(session, doc_id, "parse", "started")

            data = download(doc.storage_key)
            chunks, parser_name = parse_any(doc.source_kind, data, doc.original_filename, doc.mime_type)

            # Idempotency: a re-run replaces prior artifacts (pages cascade-delete
            # nothing else; extractions are deleted explicitly below).
            session.query(DocumentPage).filter(DocumentPage.document_id == doc_id).delete()
            session.query(TextChunk).filter(TextChunk.document_id == doc_id).delete()

            if chunks and chunks[0]["chunk_type"] == "page":
                doc.page_count = len(chunks)
                for chunk in chunks:
                    session.add(
                        DocumentPage(
                            document_id=doc_id,
                            page_number=chunk["page_number"] or 1,
                            raw_text=chunk["content"],
                            ocr_confidence=(chunk["meta"] or {}).get("ocr_confidence"),
                            layout_meta=chunk["meta"] or None,
                        )
                    )

            for chunk in chunks:
                session.add(
                    TextChunk(
                        document_id=doc_id,
                        chunk_type=chunk["chunk_type"],
                        content=chunk["content"],
                        provenance_meta=chunk["meta"] or None,
                    )
                )
            _log_event(session, doc_id, "parse", "ok", f"parser={parser_name} chunks={len(chunks)}")
    except Exception as exc:
        with session_scope() as session:
            _fail(session, doc_id, "parse", exc)
        raise
    return document_id


@celery_app.task(bind=True, base=_PipelineTask, name="processing.extract_document", queue="llm")
def extract_document(self, document_id: str) -> str:
    doc_id = uuid.UUID(document_id)
    try:
        with session_scope() as session:
            doc = _get_document(session, doc_id)
            if doc is None:
                return document_id
            _log_event(session, doc_id, "extract", "started")

            # Idempotency: drop the previous extraction (line_items and
            # validation_results go with it via DB-level ON DELETE CASCADE).
            # But human corrections must survive a reprocess — capture them first.
            prior = session.scalars(
                select(Extraction)
                .where(Extraction.document_id == doc_id)
                .order_by(Extraction.created_at.desc())
            ).first()
            human_fields: dict[str, dict] = {}
            human_line_items: list[dict] = []
            if prior is not None:
                human_fields = {
                    name: entry
                    for name, entry in (prior.fields or {}).items()
                    if isinstance(entry, dict) and entry.get("source") == "human"
                }
                prior_items = [
                    {
                        "description": li.description,
                        "quantity": li.quantity,
                        "unit_price": li.unit_price,
                        "amount": li.amount,
                        "confidence": li.confidence,
                    }
                    for li in prior.line_items
                ]
                # All-or-nothing: if the operator touched any line item, keep the
                # whole human set; otherwise the fresh extraction replaces them.
                if any(
                    (li.provenance or {}).get("source") == "human" for li in prior.line_items
                ):
                    human_line_items = prior_items

            session.query(Extraction).filter(Extraction.document_id == doc_id).delete()
            session.flush()

            chunks = session.scalars(
                select(TextChunk).where(TextChunk.document_id == doc_id).order_by(TextChunk.id)
            ).all()
            if not chunks:
                raise ValueError("no text chunks to extract from")
            text = "\n\n".join(c.content for c in chunks)
            columns = next((c.provenance_meta.get("columns") for c in chunks
                            if c.provenance_meta and c.provenance_meta.get("columns")), None)

            extraction_out = run_extraction(text, structured_columns=columns)

            fields = {name: getattr(extraction_out, name).model_dump()
                      for name in ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                                   "subtotal", "tax", "total", "currency")}
            # Start from the machine's own confidence over its field set...
            document_confidence = extraction_out.document_confidence
            # ...then human edits win over anything the machine just produced.
            fields.update(human_fields)
            if human_fields:
                # Confidence covers the merged set once an operator has touched it.
                confidences = [
                    entry.get("confidence", 0.0)
                    for entry in fields.values()
                    if isinstance(entry, dict) and entry.get("value") is not None
                ]
                document_confidence = (
                    round(sum(confidences) / len(confidences), 4) if confidences else 0.0
                )

            extraction = Extraction(
                document_id=doc_id,
                fields=fields,
                document_confidence=document_confidence,
                extraction_model="heuristics+llm" if get_processing_settings().llm_api_key else "heuristics",
            )
            source_items = human_line_items or [
                {
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "amount": item.amount,
                    "confidence": item.confidence,
                }
                for item in extraction_out.line_items
            ]
            items_source = "human" if human_line_items else "machine"
            for i, item in enumerate(source_items, start=1):
                session.add(
                    LineItem(
                        extraction=extraction,
                        position=i,
                        description=item["description"],
                        quantity=item["quantity"],
                        unit_price=item["unit_price"],
                        amount=item["amount"],
                        confidence=item["confidence"],
                        provenance={"source": items_source},
                    )
                )
            session.add(extraction)
            session.flush()
            _log_event(session, doc_id, "extract", "ok",
                       f"confidence={extraction.document_confidence} items={len(source_items)} "
                       f"human_fields={len(human_fields)}")
    except Exception as exc:
        with session_scope() as session:
            _fail(session, doc_id, "extract", exc)
        raise
    return document_id


@celery_app.task(bind=True, base=_PipelineTask, name="processing.validate_document", queue="llm")
def validate_document(self, document_id: str) -> str:
    doc_id = uuid.UUID(document_id)
    try:
        with session_scope() as session:
            doc = _get_document(session, doc_id)
            if doc is None:
                return document_id
            _log_event(session, doc_id, "validate", "started")

            extraction = session.scalars(
                select(Extraction).where(Extraction.document_id == doc_id).order_by(Extraction.created_at.desc())
            ).first()
            if extraction is None:
                raise ValueError("no extraction to validate")

            # Idempotency: a re-validation (after a correction or reprocess)
            # replaces prior findings instead of stacking duplicates.
            session.query(ValidationResult).filter(
                ValidationResult.extraction_id == extraction.id
            ).delete()
            session.flush()

            rows, status = run_all(extraction, session)
            for row in rows:
                session.add(row)
            doc.status = DocumentStatus(status).value
            _log_event(session, doc_id, "validate", "ok",
                       f"status={status} findings={len(rows)}")
    except Exception as exc:
        with session_scope() as session:
            _fail(session, doc_id, "validate", exc)
        raise
    return document_id


@celery_app.task(bind=True, base=_PipelineTask, name="processing.index_document", queue="llm")
def index_document(self, document_id: str) -> str:
    """Embed every chunk so semantic search can reach it.

    The keyword index needs nothing here — ``content_tsv`` is a generated column
    written by Postgres on insert — so this stage only writes vectors. It is
    idempotent: a reprocess overwrites each chunk's vector in place.
    """
    doc_id = uuid.UUID(document_id)
    try:
        with session_scope() as session:
            doc = _get_document(session, doc_id)
            if doc is None:
                return document_id
            _log_event(session, doc_id, "index", "started")

            chunks = session.scalars(
                select(TextChunk).where(TextChunk.document_id == doc_id).order_by(TextChunk.id)
            ).all()
            if not chunks:
                raise ValueError("index stage found no chunks")

            vectors = embed_passages([chunk.content for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector

            settings = get_embedding_settings()
            _log_event(
                session,
                doc_id,
                "index",
                "ok",
                f"chunks={len(chunks)} model={settings.model} dims={settings.dimensions}",
            )
    except Exception as exc:
        with session_scope() as session:
            _fail(session, doc_id, "index", exc)
        raise
    return document_id


def enqueue_pipeline(document_id: str) -> None:
    """Called by the api: fires the whole chain onto the queues."""
    chain(
        route_document.s(document_id),
        parse_document.s(),
        extract_document.s(),
        validate_document.s(),
        index_document.s(),
    ).apply_async()
