"""corrections — human-in-the-loop fixes; audit trail, never mutated."""

from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app_core.models.base import Base, CreatedAtMixin, UUIDPk


class Correction(Base, UUIDPk, CreatedAtMixin):
    __tablename__ = "corrections"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True  # keep the audit trail intact
    )
    field: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
