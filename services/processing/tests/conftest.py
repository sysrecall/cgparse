"""Fixtures for the processing suite.

Unit tests run with dummy provider settings. DB tests need
``TEST_DATABASE_URL`` (a dedicated Supabase dev project) and are marked
``@pytest.mark.db``.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from app_core.testing import (
    apply_migrations,
    configure_test_env,
    make_document,
    make_extraction,
    truncate_all,
)

TEST_URL = configure_test_env()


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs TEST_DATABASE_URL (dedicated dev project)")
    config.addinivalue_line("markers", "llm: calls the real LLM provider (opt-in)")


@pytest.fixture(scope="session")
def db_engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL is not set; skipping database tests")
    from app_core.db import normalize_database_url
    from sqlalchemy import create_engine

    apply_migrations(TEST_URL)
    engine = create_engine(normalize_database_url(TEST_URL), pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_database(request):
    """Truncate before every DB-marked test, never before unit tests."""
    if TEST_URL and request.node.get_closest_marker("db"):
        truncate_all(request.getfixturevalue("db_engine"))
    yield


@pytest.fixture
def db_session_factory(db_engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def db_session(db_session_factory):
    with db_session_factory() as session:
        yield session


@pytest.fixture
def document_factory(db_session):
    def factory(**overrides):
        return make_document(db_session, **overrides)

    return factory


@pytest.fixture
def extraction_factory(db_session):
    def factory(document, **kwargs):
        return make_extraction(db_session, document, **kwargs)

    return factory


@pytest.fixture
def pipeline_env(db_session_factory, monkeypatch):
    """Run pipeline stages in-process: test DB, in-memory storage, no Redis."""
    from app.queues import pipeline

    storage: dict[str, bytes] = {}
    published: list[dict] = []
    calls = SimpleNamespace(extraction=None)

    @contextmanager
    def session_scope():
        session = db_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(pipeline, "session_scope", session_scope)
    monkeypatch.setattr(pipeline, "publish", published.append)
    monkeypatch.setattr(pipeline, "download", lambda key: storage[key])
    monkeypatch.setattr(
        pipeline,
        "get_processing_settings",
        lambda: SimpleNamespace(llm_api_key=""),
    )
    monkeypatch.setattr(
        pipeline,
        "run_extraction",
        lambda text, structured_columns=None: calls.extraction,
    )
    return SimpleNamespace(
        storage=storage,
        published=published,
        calls=calls,
        session_factory=db_session_factory,
    )


@pytest.fixture
def fresh(db_session_factory):
    """Read committed rows through a brand-new session (pipeline commits elsewhere)."""

    @contextmanager
    def _fresh():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    return _fresh
