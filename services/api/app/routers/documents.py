"""documents router: upload, list, detail."""

import uuid
from typing import Any

from app_core.db import session_scope
from app_core.models.document import Document
from app_core.models.enums import DocumentStatus
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.ingest import ingest_one
from app.services.queue import enqueue_route

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def get_db() -> Any:
    yield from session_scope()


class UploadItem(BaseModel):
    filename: str
    document_id: uuid.UUID | None = None
    status: str | None = None
    error: str | None = None


class UploadResponse(BaseModel):
    items: list[UploadItem]


@router.post("", response_model=UploadResponse, status_code=202)
async def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Accept 1..N files; each is processed independently (per-file errors, never batch abort)."""
    if not files:
        raise HTTPException(status_code=422, detail="no files provided")

    items: list[UploadItem] = []
    accepted_ids: list[uuid.UUID] = []

    for file in files:
        result = await ingest_one(file, db)
        if result.error:
            items.append(UploadItem(filename=result.filename, error=result.error))
        else:
            assert result.document is not None
            items.append(
                UploadItem(
                    filename=result.filename,
                    document_id=result.document.id,
                    status=result.document.status,
                )
            )
            accepted_ids.append(result.document.id)

    db.commit()  # single transaction for the whole batch

    # Enqueue only after the rows are durable — a crash between commit and
    # enqueue is recoverable via /jobs/failed/reprocess later.
    for doc_id in accepted_ids:
        enqueue_route(doc_id)

    return UploadResponse(items=items)


class DocumentSummary(BaseModel):
    id: uuid.UUID
    original_filename: str
    source_kind: str
    status: str
    size_bytes: int
    page_count: int | None
    created_at: str


class DocumentListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: list[DocumentSummary]


@router.get("", response_model=DocumentListResponse)
def list_documents(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: DocumentStatus | None = None,
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    query = select(Document).order_by(Document.created_at.desc())
    count_query = select(func.count()).select_from(Document)
    if status:
        query = query.where(Document.status == status.value)
        count_query = count_query.where(Document.status == status.value)

    total = db.scalar(count_query) or 0
    rows = db.scalars(query.offset((page - 1) * size).limit(size)).all()
    return DocumentListResponse(
        total=total,
        page=page,
        size=size,
        items=[
            DocumentSummary(
                id=d.id,
                original_filename=d.original_filename,
                source_kind=d.source_kind,
                status=d.status,
                size_bytes=d.size_bytes,
                page_count=d.page_count,
                created_at=d.created_at.isoformat(),
            )
            for d in rows
        ],
    )


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        "id": str(document.id),
        "original_filename": document.original_filename,
        "mime_type": document.mime_type,
        "source_kind": document.source_kind,
        "status": document.status,
        "size_bytes": document.size_bytes,
        "page_count": document.page_count,
        "ocr_confidence": document.ocr_confidence,
        "failure_reason": document.failure_reason,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }
