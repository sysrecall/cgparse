"""corrections + reprocess: manual override of an extraction, and re-running the pipeline.

PATCH /api/v1/documents/{id}/corrections
    Body: {"fields": {name: value, ...}, "line_items": [ ... ] | null}
    - `fields` is a partial header update: only the keys sent are changed.
    - `line_items`, when present, replaces the whole set (all-or-nothing).
    - Every corrected value is coerced through the extraction contract and
      stamped confidence=1.0 / source="human", so a later reprocess preserves
      it and re-validation trusts it.
    Validation is re-run asynchronously; the client polls document status.

POST /api/v1/documents/{id}/reprocess?from=parse|extract
    Re-enqueue the pipeline. Human edits are preserved by the extract stage.
"""

import uuid
from decimal import Decimal
from typing import Any

from app_core.db import session_scope
from app_core.models.document import Document
from app_core.models.enums import DocumentStatus
from app_core.models.extraction import Extraction
from app_core.models.line_item import LineItem
from app_core.models.validation_result import ValidationResult
from app_core.schemas.extraction import date_to_iso, money_to_float
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.queue import enqueue_route, enqueue_validate

router = APIRouter(prefix="/api/v1/documents", tags=["corrections"])

HEADER_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)
MONEY_FIELDS = {"subtotal", "tax", "total"}
DATE_FIELDS = {"invoice_date"}
LINE_ITEM_FIELDS = ("description", "quantity", "unit_price", "amount")


def get_db() -> Any:
    with session_scope() as session:
        yield session


class LineItemIn(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class CorrectionRequest(BaseModel):
    fields: dict[str, Any] | None = None
    line_items: list[LineItemIn] | None = None


class CorrectionResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    corrected_fields: list[str]
    line_items_replaced: bool
    findings_cleared: int
    revalidation_queued: bool


def _coerce(field: str, raw: Any) -> Any:
    """Run operator input through the same contract the extractors use."""
    if raw is None:
        return None
    if field in MONEY_FIELDS:
        value = money_to_float(raw)
        if value is None:
            raise HTTPException(status_code=422, detail=f"{field}: {raw!r} is not a number")
        return value
    if field in DATE_FIELDS:
        value = date_to_iso(raw)
        if value is None:
            raise HTTPException(status_code=422, detail=f"{field}: {raw!r} is not a valid date")
        return value
    return str(raw)


def _newest_extraction(db: Session, document_id: uuid.UUID) -> Extraction | None:
    return db.scalars(
        select(Extraction)
        .where(Extraction.document_id == document_id)
        .order_by(Extraction.created_at.desc())
    ).first()


def _dec(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


@router.patch("/{document_id}/corrections", response_model=CorrectionResponse)
def correct_document(
    document_id: uuid.UUID,
    payload: CorrectionRequest,
    db: Session = Depends(get_db),
) -> CorrectionResponse:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    extraction = _newest_extraction(db, document_id)
    if extraction is None:
        raise HTTPException(status_code=409, detail="document has no extraction to correct")

    if payload.fields is None and payload.line_items is None:
        raise HTTPException(status_code=422, detail="nothing to correct")

    corrected: list[str] = []

    if payload.fields:
        unknown = set(payload.fields) - set(HEADER_FIELDS)
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown fields: {sorted(unknown)}")
        fields = dict(extraction.fields or {})
        for name, raw in payload.fields.items():
            value = _coerce(name, raw)
            fields[name] = {"value": value, "confidence": 1.0, "source": "human"}
            corrected.append(name)
        extraction.fields = fields
        # Recompute document confidence from the (now partly human) field set.
        confidences = [
            e.get("confidence", 0.0)
            for e in fields.values()
            if isinstance(e, dict) and e.get("value") is not None
        ]
        extraction.document_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        )

    items_replaced = payload.line_items is not None
    if items_replaced:
        for existing in list(extraction.line_items):
            db.delete(existing)
        db.flush()  # deletes must land before the re-inserted positions
        for i, item in enumerate(payload.line_items, start=1):  # type: ignore[union-attr]
            db.add(
                LineItem(
                    extraction_id=extraction.id,
                    position=i,
                    description=item.description,
                    quantity=_dec(item.quantity),
                    unit_price=_dec(item.unit_price),
                    amount=_dec(item.amount),
                    confidence=1.0,
                    provenance={"source": "human"},
                )
            )

    # Clear stale findings now; the async re-validation writes fresh ones.
    findings_cleared = (
        db.query(ValidationResult)
        .filter(ValidationResult.extraction_id == extraction.id)
        .delete()
    )
    document.status = DocumentStatus.PROCESSING.value
    document.failure_reason = None

    db.commit()

    enqueue_validate(document_id)
    return CorrectionResponse(
        document_id=document_id,
        status=DocumentStatus.PROCESSING.value,
        corrected_fields=corrected,
        line_items_replaced=items_replaced,
        findings_cleared=findings_cleared,
        revalidation_queued=True,
    )


class ReprocessResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    from_stage: str


@router.post("/{document_id}/reprocess", response_model=ReprocessResponse)
def reprocess_document(
    document_id: uuid.UUID,
    from_stage: str = Query("parse", alias="from", pattern="^(parse|extract)$"),
    db: Session = Depends(get_db),
) -> ReprocessResponse:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    document.status = DocumentStatus.QUEUED.value
    document.failure_reason = None
    db.commit()

    enqueue_route(document_id, from_stage=from_stage)
    return ReprocessResponse(
        document_id=document_id,
        status=DocumentStatus.QUEUED.value,
        from_stage=from_stage,
    )
