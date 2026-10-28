"""text_chunks — search index rows: keyword (tsvector, generated) + semantic (pgvector)."""

from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app_core.models.base import Base, UUIDPk
from app_core.models.enums import ChunkType

# Dimension must match the embedding model (text-embedding-3-small = 1536).
EMBEDDING_DIM = 1536


class TextChunk(Base, UUIDPk):
    __tablename__ = "text_chunks"
    __table_args__ = (
        CheckConstraint(
            f"chunk_type IN ({', '.join(repr(c.value) for c in ChunkType)})",
            name="chunk_type_valid",
        ),
        Index("ix_text_chunks_fts", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_text_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_type: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    # Generated column — maintained by Postgres, no trigger needed
    content_tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,  # null when content is null/empty
    )
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    provenance_meta: Mapped[dict | None] = mapped_column(JSONB)
