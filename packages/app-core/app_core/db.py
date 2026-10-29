"""Shared SQLAlchemy engine/session helpers for api + processing."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app_core.settings import get_shared_settings


def normalize_database_url(url: str) -> str:
    """Supabase hands out postgresql:// — SQLAlchemy needs the driver spelled out."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@lru_cache
def get_engine() -> Engine:
    settings = get_shared_settings()
    return create_engine(
        normalize_database_url(settings.database_url),
        pool_pre_ping=True,  # pooled Supabase connections can idle out — re-validate
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session: commit on success, rollback on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
