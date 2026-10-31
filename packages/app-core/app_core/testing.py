"""Test-only helpers shared by the three pytest suites.

Runtime code never imports this module. It keeps the environment bootstrap,
schema setup and row factories in one place so the api and processing suites
cannot drift apart.

Integration tests target a *dedicated* Supabase dev project, selected with
``TEST_DATABASE_URL`` (``DATABASE_URL_TEST`` is accepted as an alias). Without
that variable the DB-marked tests skip; unit tests still run.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "packages" / "app-core" / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "packages" / "app-core" / "migrations"

# CASCADE covers the FK graph, so order is irrelevant.
_ALL_TABLES = (
    "corrections",
    "processing_events",
    "validation_results",
    "line_items",
    "extractions",
    "text_chunks",
    "document_pages",
    "documents",
    "users",
)

REQUIRED_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)


def _dotenv_value(key: str) -> str | None:
    """Read a single key from the repo ``.env`` without importing live secrets.

    Only the explicitly requested key is read, so the unit-test process never
    accidentally picks up the live ``DATABASE_URL`` or provider keys.
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            cleaned = value.strip().strip('"').strip("'")
            return cleaned or None
    return None


def test_database_url() -> str | None:
    """The dedicated test project URL — never fall back to the live DATABASE_URL."""
    for key in ("TEST_DATABASE_URL", "DATABASE_URL_TEST"):
        value = os.environ.get(key) or _dotenv_value(key)
        if value:
            return value
    return None


def configure_test_env() -> str | None:
    """Set every env var the services require at import time.

    Returns the test database URL when one is configured. Dummy values keep
    unit tests importable without touching any real provider.
    """
    url = test_database_url()
    if url:
        # app_core.settings reads DATABASE_URL; point it at the test project.
        os.environ["DATABASE_URL"] = url
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
    os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")
    os.environ.setdefault("TIGRIS_BUCKET", "careguide-test")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_REGION", "auto")
    os.environ.setdefault("API_JWT_SECRET", "test")
    return url


def apply_migrations(url: str) -> None:
    """Run ``alembic upgrade head`` against the test project (idempotent)."""
    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = url
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")


def truncate_all(engine) -> None:
    """Wipe every table between tests. Test project only."""
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text(f"TRUNCATE TABLE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE")
        )


def field(value: object, confidence: float = 0.9, source: str = "heuristic") -> dict:
    return {"value": value, "confidence": confidence, "source": source}


def default_fields() -> dict[str, dict]:
    """A complete, internally consistent header field set."""
    return {
        "invoice_number": field("INV-TEST-001"),
        "invoice_date": field("2026-10-01"),
        "supplier_name": field("Acme Supplies Ltd"),
        "customer_name": field("Northwind Traders"),
        "subtotal": field(100.0),
        "tax": field(10.0),
        "total": field(110.0),
        "currency": field("USD"),
    }


def make_document(session, **overrides):
    """Insert a document row with unique filename/checksum defaults."""
    from app_core.models.document import Document

    token = uuid.uuid4().hex
    values: dict = {
        "id": uuid.uuid4(),
        "original_filename": f"test-{token[:8]}.csv",
        "checksum_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "mime_type": "text/csv",
        "source_kind": "csv",
        "storage_key": f"documents/{token}/original/test.csv",
        "size_bytes": 128,
        "status": "queued",
    }
    values.update(overrides)
    document = Document(**values)
    session.add(document)
    session.commit()
    return document


def _decimal(value: object):
    from decimal import Decimal

    return Decimal(str(value)) if value is not None else None


def make_extraction(
    session,
    document,
    *,
    fields: dict[str, dict] | None = None,
    line_items: list[dict] | None = None,
    confidence: float = 0.9,
    model: str = "test",
):
    """Insert an extraction (+ line items) for a document and commit."""
    from app_core.models.extraction import Extraction
    from app_core.models.line_item import LineItem

    extraction = Extraction(
        document_id=document.id,
        fields=fields if fields is not None else default_fields(),
        document_confidence=confidence,
        extraction_model=model,
    )
    session.add(extraction)
    session.flush()

    for position, item in enumerate(line_items or [], start=1):
        session.add(
            LineItem(
                extraction_id=extraction.id,
                position=position,
                description=item.get("description"),
                quantity=_decimal(item.get("quantity")),
                unit_price=_decimal(item.get("unit_price")),
                amount=_decimal(item.get("amount")),
                confidence=item.get("confidence", 1.0),
                provenance=item.get("provenance", {"source": "machine"}),
            )
        )
    session.commit()
    return extraction
