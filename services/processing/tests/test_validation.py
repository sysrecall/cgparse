"""Validation rule tests: all six rules, tolerances and aggregate status."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app_core.testing import default_fields

from app.validation.rules import run_all


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


class FakeSession:
    """Only the duplicate rule touches the session; default to 'no duplicate'."""

    def execute(self, *args, **kwargs):
        return _EmptyResult()


def _fields(**overrides) -> dict:
    fields = default_fields()
    for name, value in overrides.items():
        fields[name] = {"value": value}
    return fields


def _extraction(fields: dict, items: list[dict] | None = None):
    return SimpleNamespace(
        id=uuid4(),
        document_id=uuid4(),
        fields=fields,
        line_items=[
            SimpleNamespace(
                description=item.get("description"),
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                amount=item.get("amount"),
            )
            for item in (items or [])
        ],
    )


def _run(fields: dict, items: list[dict] | None = None, session=None):
    return run_all(_extraction(fields, items), session or FakeSession())


def _ids(rows) -> list[str]:
    return [row.rule_id for row in rows]


def test_clean_extraction_is_validated():
    rows, status = _run(
        _fields(),
        [{"description": "Widget", "quantity": 2, "unit_price": 50, "amount": 100}],
    )
    assert rows == []
    assert status == "validated"


@pytest.mark.parametrize("name", list(default_fields()))
def test_each_required_field_missing_is_an_error(name):
    rows, status = _run(_fields(**{name: None}))
    matching = [row for row in rows if row.rule_id == "missing_field"]
    assert len(matching) == 1
    assert matching[0].field == name
    assert matching[0].severity == "error"
    assert status == "needs_review"


def test_empty_string_counts_as_missing():
    rows, status = _run(_fields(currency=""))
    assert [row.field for row in rows if row.rule_id == "missing_field"] == ["currency"]
    assert status == "needs_review"


def test_non_iso_date_is_a_format_error():
    rows, status = _run(_fields(invoice_date="10/01/2026"))
    assert _ids(rows) == ["type_and_format"]
    assert rows[0].field == "invoice_date"
    assert status == "needs_review"


@pytest.mark.parametrize("name", ["subtotal", "tax", "total"])
def test_non_numeric_money_is_a_format_error(name):
    rows, status = _run(_fields(**{name: "not-money"}))
    assert [row.field for row in rows if row.rule_id == "type_and_format"] == [name]
    assert status == "needs_review"


def test_comma_formatted_money_strings_are_numeric():
    rows, status = _run(
        _fields(subtotal="4,500.00", tax="450.00", total="4,950.00"),
        [{"description": "Copper", "amount": "4,500.00"}],
    )
    assert rows == []
    assert status == "validated"


def test_line_items_must_sum_to_subtotal():
    rows, status = _run(
        _fields(subtotal=100.0),
        [
            {"description": "A", "amount": 60},
            {"description": "B", "amount": 30},
        ],
    )
    assert _ids(rows) == ["line_items_sum"]
    assert rows[0].field == "line_items"
    assert "90" in rows[0].message and "100" in rows[0].message
    assert status == "needs_review"


def test_line_items_sum_tolerance_is_one_cent():
    rows, status = _run(
        _fields(subtotal=100.0),
        [{"description": "A", "amount": 100.01}],
    )
    assert rows == []
    assert status == "validated"


def test_line_items_sum_is_skipped_without_items():
    rows, _ = _run(_fields(subtotal=100.0), [])
    assert rows == []


def test_subtotal_plus_tax_must_equal_total():
    rows, status = _run(_fields(subtotal=100.0, tax=10.0, total=111.0))
    assert _ids(rows) == ["subtotal_tax_total"]
    assert rows[0].field == "total"
    assert status == "needs_review"


def test_subtotal_tax_total_tolerance_is_one_cent():
    rows, _ = _run(_fields(subtotal=100.0, tax=10.0, total=110.01))
    assert rows == []


def test_subtotal_tax_total_is_skipped_when_a_value_is_missing():
    rows, _ = _run(_fields(total=None))
    assert [row for row in rows if row.rule_id == "subtotal_tax_total"] == []


def test_negative_line_item_values_are_flagged():
    rows, status = _run(
        _fields(subtotal=0.0, tax=0.0, total=0.0),
        [{"description": "Credit", "quantity": -1, "unit_price": -5, "amount": -5}],
    )
    negatives = [row for row in rows if row.rule_id == "negative_or_impossible_values"]
    assert len(negatives) == 3
    assert all(row.field == "line_items" for row in negatives)
    assert status == "needs_review"


def test_zero_line_item_values_are_allowed():
    rows, _ = _run(
        _fields(subtotal=0.0, tax=0.0, total=0.0),
        [{"description": "Free", "quantity": 0, "unit_price": 0, "amount": 0}],
    )
    assert rows == []


def test_multiple_rules_report_together():
    rows, status = _run(
        _fields(currency=None, subtotal=100.0, tax=10.0, total=120.0),
        [{"description": "A", "amount": 90}],
    )
    assert set(_ids(rows)) == {"missing_field", "line_items_sum", "subtotal_tax_total"}
    assert status == "needs_review"


@pytest.mark.db
def test_duplicate_invoice_is_a_warning_not_an_error(db_session, document_factory, extraction_factory):
    first_doc = document_factory()
    extraction_factory(
        first_doc,
        fields=_fields(),
        line_items=[{"description": "A", "amount": 100}],
    )

    second_doc = document_factory()
    second = extraction_factory(
        second_doc,
        fields=_fields(),
        line_items=[{"description": "A", "amount": 100}],
    )

    rows, status = run_all(second, db_session)

    duplicates = [row for row in rows if row.rule_id == "duplicate_invoice"]
    assert len(duplicates) == 1
    assert duplicates[0].severity == "warning"
    assert duplicates[0].field == "invoice_number"
    # A warning alone does not move the document to review.
    assert status == "validated"


@pytest.mark.db
def test_duplicate_rule_is_skipped_without_supplier_or_number(db_session, document_factory, extraction_factory):
    document_factory()
    document = document_factory()
    extraction = extraction_factory(document, fields=_fields(invoice_number=None))

    rows, status = run_all(extraction, db_session)

    assert [row for row in rows if row.rule_id == "duplicate_invoice"] == []
    assert "missing_field" in _ids(rows)
    assert status == "needs_review"
