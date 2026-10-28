"""line_items — invoice lines, money as NUMERIC(12,2) per the schema decision."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app_core.models.base import Base, UUIDPk


class LineItem(Base, UUIDPk):
    __tablename__ = "line_items"
    __table_args__ = (
        UniqueConstraint("extraction_id", "position", name="uq_line_items_extraction_pos"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
    )

    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[dict | None] = mapped_column(JSONB)

    extraction = relationship("Extraction", back_populates="line_items")
