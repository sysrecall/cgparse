"""initial schema — 9 tables, pgvector extension, FTS generated column, HNSW index

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    # pgvector must exist before the embedding column is created.
    # (Supabase: enabled by default as a trusted extension.)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "role IN ('admin', 'reviewer', 'viewer')", name="ck_users_role_valid"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'validated', 'needs_review', 'failed')",
            name="ck_documents_status_valid",
        ),
        sa.CheckConstraint(
            "source_kind IN ('pdf', 'image', 'spreadsheet', 'csv')",
            name="ck_documents_source_kind_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("ix_documents_checksum_sha256", "documents", ["checksum_sha256"], unique=True)
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("preview_storage_key", sa.Text(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("layout_meta", JSONB(), nullable=True),
        sa.CheckConstraint("page_number >= 1", name="ck_document_pages_page_number_positive"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name="fk_document_pages_document_id_documents", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_pages"),
        sa.UniqueConstraint("document_id", "page_number", name="uq_document_pages_doc_page"),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])

    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("fields", JSONB(), nullable=False),
        sa.Column("document_confidence", sa.Float(), nullable=False),
        sa.Column("extraction_model", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name="fk_extractions_document_id_documents", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_extractions"),
    )
    op.create_index("ix_extractions_document_id", "extractions", ["document_id"])

    op.create_table(
        "line_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provenance", JSONB(), nullable=True),
        sa.CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_line_items_quantity_non_negative"),
        sa.CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="ck_line_items_unit_price_non_negative"),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_line_items_amount_non_negative"),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["extractions.id"],
            name="fk_line_items_extraction_id_extractions", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_line_items"),
        sa.UniqueConstraint("extraction_id", "position", name="uq_line_items_extraction_pos"),
    )
    op.create_index("ix_line_items_extraction_id", "line_items", ["extraction_id"])

    op.create_table(
        "validation_results",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("field", sa.String(length=50), nullable=True),
        sa.Column("auto_resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "severity IN ('error', 'warning', 'info')", name="ck_validation_results_severity_valid"
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["extractions.id"],
            name="fk_validation_results_extraction_id_extractions", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_validation_results"),
    )
    op.create_index("ix_validation_results_extraction_id", "validation_results", ["extraction_id"])

    op.create_table(
        "processing_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name="fk_processing_events_document_id_documents", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_events"),
    )
    op.create_index("ix_processing_events_document_id", "processing_events", ["document_id"])

    op.create_table(
        "corrections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=50), nullable=False),
        sa.Column("old_value", JSONB(), nullable=True),
        sa.Column("new_value", JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name="fk_corrections_document_id_documents", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_corrections_user_id_users", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_corrections"),
    )
    op.create_index("ix_corrections_document_id", "corrections", ["document_id"])
    op.create_index("ix_corrections_user_id", "corrections", ["user_id"])

    op.create_table(
        "text_chunks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_type", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "content_tsv", TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("provenance_meta", JSONB(), nullable=True),
        sa.CheckConstraint(
            "chunk_type IN ('page', 'row', 'field')", name="ck_text_chunks_chunk_type_valid"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"],
            name="fk_text_chunks_document_id_documents", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_text_chunks"),
    )
    op.create_index("ix_text_chunks_document_id", "text_chunks", ["document_id"])
    op.create_index("ix_text_chunks_fts", "text_chunks", ["content_tsv"], postgresql_using="gin")
    op.create_index(
        "ix_text_chunks_embedding", "text_chunks", ["embedding"],
        postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("text_chunks")
    op.drop_table("corrections")
    op.drop_table("processing_events")
    op.drop_table("validation_results")
    op.drop_table("line_items")
    op.drop_table("extractions")
    op.drop_table("document_pages")
    op.drop_table("documents")
    op.drop_table("users")
