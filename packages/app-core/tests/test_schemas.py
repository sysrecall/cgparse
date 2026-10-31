"""Extraction-contract tests: the anti-hallucination rules live here."""

import pytest

from app_core.schemas.extraction import (
    ExtractionOut,
    FieldOut,
    LineItemOut,
    date_to_iso,
    money_to_float,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (12, 12.0),
        (12.5, 12.5),
        ("4500.00", 4500.0),
        ("$4,500.00", 4500.0),
        ("EUR 1.234,56", 1.23456),  # no locale inference: strips separators literally
        ("  99 ", 99.0),
        ("-15.50", -15.5),
        ("", None),
        ("-", None),
        (".", None),
        ("not a number", None),
        ("12.3.4", None),
    ],
)
def test_money_to_float(raw, expected):
    assert money_to_float(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("2026-10-01", "2026-10-01"),
        ("2026/10/01", "2026-10-01"),
        ("October 1, 2026", "2026-10-01"),
        ("01.10.2026", "2026-01-10"),  # dayfirst=False, yearfirst=False
        ("not a date", None),
        ("31/02/2026", None),
    ],
)
def test_date_to_iso(raw, expected):
    assert date_to_iso(raw) == expected


def test_field_confidence_is_bounded():
    assert FieldOut().confidence == 0.0
    with pytest.raises(ValueError):
        FieldOut(confidence=1.5)
    with pytest.raises(ValueError):
        FieldOut(confidence=-0.1)


def test_extraction_normalizes_money_strings_and_dates():
    extraction = ExtractionOut.model_validate(
        {
            "invoice_number": {"value": "INV-1", "confidence": 0.9},
            "invoice_date": {"value": "October 1, 2026", "confidence": 0.8},
            "subtotal": {"value": "$1,200.50", "confidence": 0.9},
            "tax": {"value": "120.05", "confidence": 0.9},
            "total": {"value": "1,320.55", "confidence": 0.9},
            "currency": {"value": "usd", "confidence": 0.9},
        }
    )
    assert extraction.invoice_date.value == "2026-10-01"
    assert extraction.subtotal.value == 1200.5
    assert extraction.tax.value == 120.05
    assert extraction.total.value == 1320.55
    # currency is passed through as-is; validation owns normalization
    assert extraction.currency.value == "usd"


def test_unparseable_values_are_dropped_not_guessed():
    extraction = ExtractionOut.model_validate(
        {
            "invoice_date": {"value": "31/02/2026", "confidence": 0.95},
            "subtotal": {"value": "n/a", "confidence": 0.95},
        }
    )
    assert extraction.invoice_date.value is None
    assert extraction.invoice_date.confidence == 0.0
    assert extraction.subtotal.value is None
    assert extraction.subtotal.confidence == 0.0


def test_missing_fields_default_to_null_with_zero_confidence():
    extraction = ExtractionOut()
    for name in (
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
        "currency",
    ):
        entry = getattr(extraction, name)
        assert entry.value is None
        assert entry.confidence == 0.0
    assert extraction.line_items == []
    assert extraction.document_confidence == 0.0


def test_line_item_numbers_are_coerced():
    item = LineItemOut(
        description="Widget",
        quantity="2",
        unit_price="$10.00",
        amount="20.00",
    )
    assert (item.quantity, item.unit_price, item.amount) == (2.0, 10.0, 20.0)


def test_line_item_bad_numbers_become_null():
    item = LineItemOut(quantity="two", unit_price="free", amount="?")
    assert item.quantity is None
    assert item.unit_price is None
    assert item.amount is None
