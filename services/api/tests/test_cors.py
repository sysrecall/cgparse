"""CORS origin parsing: a stray slash in config must not block the browser."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import _cors_origins


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://app.example", ["https://app.example"]),
        # The bug this guards: browsers never send the trailing slash.
        ("https://app.example/", ["https://app.example"]),
        (" https://a.example/ , https://b.example ", ["https://a.example", "https://b.example"]),
        ("https://a.example,,  ", ["https://a.example"]),
        ("https://a.example,https://a.example/", ["https://a.example"]),
        ("", []),
    ],
)
def test_cors_origins_are_normalized(raw, expected):
    assert _cors_origins(raw) == expected


def test_trailing_slash_config_still_allows_the_browser_origin(monkeypatch):
    from app import main

    monkeypatch.setattr(
        main,
        "get_api_settings",
        lambda: type("S", (), {"cors_origins": "https://app.example/"})(),
    )
    monkeypatch.setattr(main, "get_shared_settings", lambda: None)
    app: FastAPI = main.create_app()

    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example"
