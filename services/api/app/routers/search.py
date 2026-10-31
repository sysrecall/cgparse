"""Search: keyword (FTS + filename) now; semantic deferred (returns 501).

Result shape: one entry per document carrying ALL matching snippets.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from app_core.db import session_scope
from app_core.models.document import Document
from app_core.models.enums import DocumentStatus
from app_core.models.extraction import Extraction
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Numeric, cast, func, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1/search", tags=["search"])

SNIPPET_CHARS = 400


def get_db() -> Any:
    with session_scope() as session:
        yield session


class Snippet(BaseModel):
    chunk_type: str
    text: str
    page_number: int | None = None


class SearchHit(BaseModel):
    id: str
    original_filename: str
    status: str
    source_kind: str
    created_at: str
    rank: float
    snippets: list[Snippet]


class SearchResponse(BaseModel):
    query: str
    semantic: bool
    total: int
    page: int
    size: int
    items: list[SearchHit]


def _fts_hits(db: Session, q: str) -> dict[str, dict]:
    """Keyword hits from chunk text, grouped by document with every snippet."""
    rows = db.execute(
        text(
            """
            SELECT tc.document_id,
                   tc.content,
                   tc.chunk_type,
                   tc.provenance_meta->>'row' AS row_number,
                   ts_rank(tc.content_tsv, websearch_to_tsquery('english', :q)) AS rank
            FROM text_chunks tc
            WHERE tc.content_tsv @@ websearch_to_tsquery('english', :q)
            ORDER BY rank DESC
            """
        ),
        {"q": q},
    ).mappings()

    hits: dict[str, dict] = {}
    for row in rows:
        doc_id = str(row["document_id"])
        entry = hits.setdefault(doc_id, {"rank": 0.0, "snippets": []})
        entry["rank"] = max(entry["rank"], float(row["rank"] or 0.0))
        content = (row["content"] or "").strip()
        entry["snippets"].append(
            Snippet(
                chunk_type=row["chunk_type"],
                text=content[:SNIPPET_CHARS] + ("…" if len(content) > SNIPPET_CHARS else ""),
                page_number=int(row["row_number"]) if row["row_number"] else None,
            ).model_dump()
        )
    return hits


def _apply_filters(stmt, **filters):
    if filters.get("status"):
        stmt = stmt.where(Document.status == filters["status"])
    if filters.get("date_from"):
        stmt = stmt.where(Document.created_at >= filters["date_from"])
    if filters.get("date_to"):
        stmt = stmt.where(Document.created_at <= filters["date_to"])
    return stmt


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Keyword query (FTS + filename)"),
    semantic: bool = Query(False, description="Semantic search — not implemented yet"),
    status: DocumentStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    supplier: str | None = None,
    min_total: Decimal | None = None,
    currency: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SearchResponse:
    if semantic:
        raise HTTPException(
            status_code=501,
            detail="semantic search is not implemented yet (embeddings deferred); use semantic=false",
        )

    hits = _fts_hits(db, q)

    # Filename matches join the same result set (metadata search alongside content).
    filename_matches = db.scalars(
        _apply_filters(
            select(Document).where(Document.original_filename.ilike(f"%{q}%")),
            status=status.value if status else None,
            date_from=date_from,
            date_to=date_to,
        )
    ).all()
    for doc in filename_matches:
        entry = hits.setdefault(str(doc.id), {"rank": 0.0, "snippets": []})
        entry["rank"] = max(entry["rank"], 0.05)  # filename hits rank below content hits

    if not hits:
        return SearchResponse(query=q, semantic=False, total=0, page=page, size=size, items=[])

    docs = db.scalars(
        _apply_filters(
            select(Document).where(Document.id.in_([h for h in hits])),
            status=status.value if status else None,
            date_from=date_from,
            date_to=date_to,
        )
    ).all()

    # Extraction-derived filters (supplier / min_total / currency) against the
    # newest extraction per document.
    if supplier or min_total is not None or currency:
        newest = (
            select(Extraction.document_id, Extraction.fields)
            .ext(distinct_on(Extraction.document_id))
            .order_by(Extraction.document_id, Extraction.created_at.desc())
            .subquery()
        )
        stmt = select(newest.c.document_id).select_from(newest)
        if supplier:
            stmt = stmt.where(newest.c.fields["supplier_name"]["value"].astext.ilike(f"%{supplier}%"))
        if currency:
            stmt = stmt.where(func.upper(newest.c.fields["currency"]["value"].astext) == currency.upper())
        if min_total is not None:
            stmt = stmt.where(cast(newest.c.fields["total"]["value"].astext, Numeric) >= min_total)
        allowed = {str(r[0]) for r in db.execute(stmt)}
        docs = [d for d in docs if str(d.id) in allowed]

    ordered = sorted(docs, key=lambda d: (-hits[str(d.id)]["rank"], d.created_at), reverse=False)
    total = len(ordered)
    window = ordered[(page - 1) * size : page * size]

    items = [
        SearchHit(
            id=str(d.id),
            original_filename=d.original_filename,
            status=d.status,
            source_kind=d.source_kind,
            created_at=d.created_at.isoformat(),
            rank=round(hits[str(d.id)]["rank"], 6),
            snippets=[Snippet(**s) for s in hits[str(d.id)]["snippets"]],
        )
        for d in window
    ]
    return SearchResponse(query=q, semantic=False, total=total, page=page, size=size, items=items)
