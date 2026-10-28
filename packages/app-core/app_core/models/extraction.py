"""extractions — the LLM/heuristic output for a document (header fields + confidences)."""

from uuid import UUID

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app_core.models.base import Base, CreatedAtMixin, UUIDPk
from app_core.models.line_item import LineItem
from app_core.models.validation_result import ValidationResult


class Extraction(Base, UUIDPk, CreatedAtMixin):
    __tablename__ = "extractions"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    # All core header fields as {value, confidence, source_span} objects
    fields: Mapped[dict] = mapped_column(JSONB)
    document_confidence: Mapped[float] = mapped_column(Float)
    extraction_model: Mapped[str] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)

    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan", order_by="LineItem.position"
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )
