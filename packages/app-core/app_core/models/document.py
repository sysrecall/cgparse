"""documents — one row per ingested file; the pipeline's central state machine."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app_core.models.base import Base, CreatedAtMixin, UUIDPk
from app_core.models.enums import DocumentStatus, SourceKind

if TYPE_CHECKING:
    from app_core.models.document_page import DocumentPage


class Document(Base, UUIDPk, CreatedAtMixin):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s.value) for s in DocumentStatus)})",
            name="status_valid",
        ),
        CheckConstraint(
            f"source_kind IN ({', '.join(repr(k.value) for k in SourceKind)})",
            name="source_kind_valid",
        ),
    )

    original_filename: Mapped[str] = mapped_column(Text)
    checksum_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    source_kind: Mapped[str] = mapped_column(String(20))
    storage_key: Mapped[str] = mapped_column(Text)  # Tigris object key — bytes live there
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20),
        default=DocumentStatus.QUEUED.value,
        server_default=DocumentStatus.QUEUED.value,
        index=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
