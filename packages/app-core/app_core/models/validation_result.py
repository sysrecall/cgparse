"""validation_results — output of the rule engine; feeds the review queue directly."""

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app_core.models.base import Base, CreatedAtMixin, UUIDPk
from app_core.models.enums import Severity


class ValidationResult(Base, UUIDPk, CreatedAtMixin):
    __tablename__ = "validation_results"
    __table_args__ = (
        CheckConstraint(
            f"severity IN ({', '.join(repr(s.value) for s in Severity)})",
            name="severity_valid",
        ),
    )

    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(50))  # e.g. missing_field, subtotal_tax_total
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    field: Mapped[str | None] = mapped_column(String(50))  # offending field, if any
    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    extraction = relationship("Extraction", back_populates="validation_results")
