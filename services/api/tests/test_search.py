"""Search: FTS + filename grouping, filters, pagination, semantic 501."""

from datetime import UTC, datetime, timedelta

import pytest
from app_core.models.text_chunk import TextChunk
from app_core.testing import default_fields

URL = "/api/v1/search"


def _add_chunk(db_session, document, content, *, chunk_type="row", meta=None):
    db_session.add(
        TextChunk(
            document_id=document.id,
            chunk_type=chunk_type,
            content=content,
            provenance_meta=meta,
        )
    )
    db_session.commit()


def _fields(**overrides):
    fields = default_fields()
    for name, value in overrides.items():
        fields[name] = {"value": value, "confidence": 0.9, "source": "heuristic"}
    return fields


def test_semantic_search_returns_501(client):
    response = client.get(URL, params={"q": "invoice", "semantic": "true"})

    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"]


def test_search_requires_a_query(client):
    assert client.get(URL).status_code == 422
    assert client.get(URL, params={"q": ""}).status_code == 422


@pytest.mark.db
def test_search_without_matches_is_empty(client):
    response = client.get(URL, params={"q": "zzzznotfound"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "zzzznotfound",
        "semantic": False,
        "total": 0,
        "page": 1,
        "size": 20,
        "items": [],
    }


@pytest.mark.db
def test_search_groups_all_matching_chunks_per_document(client, db_session, document_factory):
    document = document_factory(original_filename="invoice.csv")
    _add_chunk(db_session, document, "Widget assembly, quantity two", meta={"row": 1})
    _add_chunk(db_session, document, "Spare widget included", chunk_type="field", meta={"row": 2})

    body = client.get(URL, params={"q": "widget"}).json()

    assert body["total"] == 1
    hit = body["items"][0]
    assert hit["id"] == str(document.id)
    assert hit["original_filename"] == "invoice.csv"
    assert len(hit["snippets"]) == 2
    assert {snippet["chunk_type"] for snippet in hit["snippets"]} == {"row", "field"}
    assert hit["rank"] > 0


@pytest.mark.db
def test_search_matches_the_filename(client, document_factory):
    document = document_factory(original_filename="widget-report.csv")

    body = client.get(URL, params={"q": "widget"}).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == str(document.id)
    assert body["items"][0]["snippets"] == []
    assert body["items"][0]["rank"] == 0.05


@pytest.mark.db
def test_content_hits_rank_above_filename_hits(client, db_session, document_factory):
    now = datetime.now(UTC)
    filename_doc = document_factory(
        original_filename="widget-index.csv", created_at=now + timedelta(minutes=1)
    )
    content_doc = document_factory(original_filename="other.csv", created_at=now)
    _add_chunk(db_session, content_doc, "the widget appears in this row")

    body = client.get(URL, params={"q": "widget"}).json()

    assert [item["id"] for item in body["items"]] == [str(content_doc.id), str(filename_doc.id)]


@pytest.mark.db
def test_search_snippets_are_truncated(client, db_session, document_factory):
    document = document_factory()
    _add_chunk(db_session, document, "widget " + "x" * 450)

    body = client.get(URL, params={"q": "widget"}).json()

    snippet = body["items"][0]["snippets"][0]
    assert len(snippet["text"]) == 401
    assert snippet["text"].endswith("…")


@pytest.mark.db
def test_search_filters_by_status(client, db_session, document_factory):
    validated = document_factory(original_filename="a.csv", status="validated")
    review = document_factory(original_filename="b.csv", status="needs_review")
    _add_chunk(db_session, validated, "widget one")
    _add_chunk(db_session, review, "widget two")

    body = client.get(URL, params={"q": "widget", "status": "needs_review"}).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == str(review.id)


@pytest.mark.db
def test_search_filters_by_date_range(client, db_session, document_factory):
    now = datetime.now(UTC)
    old = document_factory(original_filename="old.csv", created_at=now - timedelta(days=10))
    recent = document_factory(original_filename="recent.csv", created_at=now)
    _add_chunk(db_session, old, "widget old")
    _add_chunk(db_session, recent, "widget recent")

    body = client.get(
        URL,
        params={
            "q": "widget",
            "date_from": (now - timedelta(days=1)).isoformat(),
        },
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == str(recent.id)


@pytest.mark.db
def test_search_filters_by_extraction_fields(
    client, db_session, document_factory, extraction_factory
):
    acme = document_factory(original_filename="acme.csv")
    gamma = document_factory(original_filename="gamma.csv")
    _add_chunk(db_session, acme, "widget acme")
    _add_chunk(db_session, gamma, "widget gamma")
    extraction_factory(
        acme,
        fields=_fields(supplier_name="Acme Supplies Ltd", total=4950.0, currency="USD"),
    )
    extraction_factory(
        gamma,
        fields=_fields(supplier_name="Gamma Manufacturing", total=100.0, currency="EUR"),
    )

    by_supplier = client.get(URL, params={"q": "widget", "supplier": "acme"}).json()
    by_total = client.get(URL, params={"q": "widget", "min_total": 1000}).json()
    by_currency = client.get(URL, params={"q": "widget", "currency": "eur"}).json()

    assert [item["id"] for item in by_supplier["items"]] == [str(acme.id)]
    assert [item["id"] for item in by_total["items"]] == [str(acme.id)]
    assert [item["id"] for item in by_currency["items"]] == [str(gamma.id)]


@pytest.mark.db
def test_search_paginates(client, db_session, document_factory):
    now = datetime.now(UTC)
    documents = [
        document_factory(
            original_filename=f"doc-{index}.csv",
            created_at=now + timedelta(minutes=index),
        )
        for index in range(3)
    ]
    for document in documents:
        _add_chunk(db_session, document, "widget row")

    first = client.get(URL, params={"q": "widget", "page": 1, "size": 2}).json()
    second = client.get(URL, params={"q": "widget", "page": 2, "size": 2}).json()

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]} == set()
