"""Fixtures for the api suite.

DB tests run against a dedicated Supabase dev project (``TEST_DATABASE_URL``)
and are marked ``@pytest.mark.db``. Provider calls are replaced with recorders.
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
    if request.node.get_closest_marker("db"):
        if not TEST_URL:
            pytest.skip("TEST_DATABASE_URL is not set; skipping database tests")
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
def fresh(db_session_factory):
    @contextmanager
    def _fresh():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    return _fresh


@pytest.fixture
def recorded():
    """Captures storage/queue calls instead of touching providers."""
    return SimpleNamespace(stored={}, enqueued=[], deleted=[])


@pytest.fixture
def client(recorded, monkeypatch):
    from app_core.db import normalize_database_url
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.main import app
    from app.routers import corrections, documents, search
    from app.services import ingest

    # Built independently of db_engine so unit tests that never touch Postgres
    # (validation-only requests) do not skip when TEST_DATABASE_URL is absent.
    # create_engine is lazy: no connection is opened until the endpoint queries.
    url = TEST_URL or "postgresql+psycopg://test:test@127.0.0.1:5432/test"
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[documents.get_db] = override_get_db
    app.dependency_overrides[corrections.get_db] = override_get_db
    app.dependency_overrides[search.get_db] = override_get_db

    def record_route(*args, **kwargs):
        recorded.enqueued.append(("route", args, kwargs))

    def record_validate(*args, **kwargs):
        recorded.enqueued.append(("validate", args, kwargs))

    monkeypatch.setattr(documents, "enqueue_route", record_route)
    monkeypatch.setattr(corrections, "enqueue_route", record_route)
    monkeypatch.setattr(corrections, "enqueue_validate", record_validate)

    def fake_upload(key, stream, content_type):
        recorded.stored[key] = {
            "content_type": content_type,
            "data": stream.read(),
        }

    monkeypatch.setattr(ingest, "upload_stream", fake_upload)
    monkeypatch.setattr(ingest, "delete_object", recorded.deleted.append)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()
