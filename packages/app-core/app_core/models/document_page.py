"""document_pages — per-page raw text (pdfplumber or OCR) + preview + OCR confidence."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app_core.models.base import Base, UUIDPk


class DocumentPage(Base, UUIDPk):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_pages_doc_page"),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text)
    preview_storage_key: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    layout_meta: Mapped[dict | None] = mapped_column(JSONB)

    document = relationship("Document", back_populates="pages")
