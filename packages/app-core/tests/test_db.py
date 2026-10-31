"""DB URL normalization: Supabase hands out plain postgresql:// URLs."""

import pytest

from app_core.db import normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://user:pass@host:6543/db",
            "postgresql+psycopg://user:pass@host:6543/db",
        ),
        (
            "postgresql+psycopg://user:pass@host:6543/db",
            "postgresql+psycopg://user:pass@host:6543/db",
        ),
        ("sqlite:///local.db", "sqlite:///local.db"),
    ],
)
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_normalize_only_rewrites_the_scheme_once():
    raw = "postgresql://u:p@h/db?options=postgresql://nested"
    normalized = normalize_database_url(raw)
    assert normalized.startswith("postgresql+psycopg://")
    assert "postgresql://nested" in normalized
