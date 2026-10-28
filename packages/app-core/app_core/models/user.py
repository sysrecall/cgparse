"""users — authentication + role-based access (admin | reviewer | viewer)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app_core.models.base import Base, CreatedAtMixin, UUIDPk
from app_core.models.enums import UserRole


class User(Base, UUIDPk, CreatedAtMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            f"role IN ({', '.join(repr(r.value) for r in UserRole)})",
            name="role_valid",
        ),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.VIEWER.value)

    created_at: Mapped[datetime] = CreatedAtMixin.created_at
