"""processing_events — append-only per-stage history for a document."""

from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app_core.models.base import Base, CreatedAtMixin, UUIDPk


class ProcessingEvent(Base, UUIDPk, CreatedAtMixin):
    __tablename__ = "processing_events"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(30))  # route | parse | ocr | llm | validate | index
    status: Mapped[str] = mapped_column(String(30))  # started | ok | retrying | failed
    detail: Mapped[str | None] = mapped_column(Text)
