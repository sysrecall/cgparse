"""Search: keyword (FTS + filename) and hybrid semantic search.

Result shape: one entry per document carrying the best matching snippets.

`semantic=false` keeps the original keyword ranking (`ts_rank`, filename hits
below content hits). `semantic=true` embeds the query, pulls the nearest chunks
from pgvector, and fuses both lists with reciprocal rank fusion — exact tokens
(invoice numbers, supplier names) come from FTS, paraphrases from the vectors.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from app_core.clients.embeddings import EmbeddingError, embed_query
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
# Reciprocal rank fusion constant (the value from the original RRF paper):
# damps the difference between the top ranks so neither list dominates.
RRF_K = 60
# Chunks returned by the vector query before grouping by document.
VECTOR_CANDIDATES = 200
# Snippets per document in semantic mode (keyword mode still returns all hits).
SEMANTIC_SNIPPETS = 5


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


def _snippet(content: str, chunk_type: str, row_number: Any) -> dict:
    content = (content or "").strip()
    return Snippet(
        chunk_type=chunk_type,
        text=content[:SNIPPET_CHARS] + ("…" if len(content) > SNIPPET_CHARS else ""),
        page_number=int(row_number) if row_number else None,
    ).model_dump()


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
        entry["snippets"].append(_snippet(row["content"], row["chunk_type"], row["row_number"]))
    return hits


def _vector_hits(db: Session, q: str, limit: int = VECTOR_CANDIDATES) -> dict[str, dict]:
    """Nearest chunks by cosine distance, grouped by document.

    The query embedding is asymmetric (`input_type="query"`); passages were
    embedded with `input_type="passage"`. Chunks without a vector (documents
    indexed before embeddings existed) are skipped rather than scoring as zero.
    """
    vector = embed_query(q)
    literal = "[" + ",".join(f"{value:.8f}" for value in vector) + "]"

    rows = db.execute(
        text(
            """
            SELECT tc.document_id,
                   tc.content,
                   tc.chunk_type,
                   tc.provenance_meta->>'row' AS row_number,
                   1 - (tc.embedding <=> CAST(:vec AS vector)) AS score
            FROM text_chunks tc
            WHERE tc.embedding IS NOT NULL
            ORDER BY tc.embedding <=> CAST(:vec AS vector)
            LIMIT :limit
            """
        ),
        {"vec": literal, "limit": limit},
    ).mappings()

    hits: dict[str, dict] = {}
    for row in rows:
        doc_id = str(row["document_id"])
        entry = hits.setdefault(doc_id, {"score": -1.0, "snippets": []})
        entry["score"] = max(entry["score"], float(row["score"] or 0.0))
        entry["snippets"].append(_snippet(row["content"], row["chunk_type"], row["row_number"]))
    return hits


def _fuse(fts: dict[str, dict], vector: dict[str, dict]) -> dict[str, dict]:
    """Reciprocal rank fusion of the keyword and vector result lists."""
    fused: dict[str, dict] = {}
    ordered_lists = (
        sorted(fts, key=lambda doc_id: -fts[doc_id]["rank"]),
        sorted(vector, key=lambda doc_id: -vector[doc_id]["score"]),
    )
    for ordered in ordered_lists:
        for position, doc_id in enumerate(ordered, start=1):
            entry = fused.setdefault(doc_id, {"rank": 0.0, "snippets": []})
            entry["rank"] += 1.0 / (RRF_K + position)

    for doc_id, entry in fused.items():
        merged: list[dict] = []
        seen: set[str] = set()
        # Vector snippets first: they explain why a semantic-only hit appeared.
        for source in (vector.get(doc_id), fts.get(doc_id)):
            for snippet in (source or {}).get("snippets", []):
                if snippet["text"] in seen:
                    continue
                seen.add(snippet["text"])
                merged.append(snippet)
                if len(merged) >= SEMANTIC_SNIPPETS:
                    break
            if len(merged) >= SEMANTIC_SNIPPETS:
                break
        entry["snippets"] = merged
    return fused


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
    q: str = Query(..., min_length=1, description="Query text (keyword or semantic)"),
    semantic: bool = Query(
        False, description="Hybrid search: FTS + pgvector, fused with reciprocal rank"
    ),
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

    if semantic:
        try:
            hits = _fuse(hits, _vector_hits(db, q))
        except EmbeddingError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"semantic search unavailable: {exc}",
            ) from exc

    if not hits:
        return SearchResponse(
            query=q, semantic=semantic, total=0, page=page, size=size, items=[]
        )

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
    return SearchResponse(
        query=q, semantic=semantic, total=total, page=page, size=size, items=items
    )
