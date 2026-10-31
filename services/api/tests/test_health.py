"""Health endpoint: the probe Render (and most load balancers) actually sends."""

import pytest


@pytest.mark.parametrize("method", ["get", "head"])
def test_health_answers_probes(client, method):
    response = getattr(client, method)("/health")

    assert response.status_code == 200


def test_health_get_returns_the_status_body(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_head_has_no_body(client):
    response = client.head("/health")

    assert response.status_code == 200
    assert response.text == ""
