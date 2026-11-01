"""Extraction tests: heuristics first, LLM fills gaps, nothing is invented."""

import hashlib

import pytest
from app_core.schemas.extraction import ExtractionOut, money_to_float

from app.llm import extract as extraction

HEADER_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)

INVOICE_TEXT = """INVOICE
Invoice Number: INV-2026-0042
Invoice Date: 2026-10-05
Supplier: Acme Supplies Ltd
Customer: Northwind Traders
Subtotal: 4,500.00
Tax: 450.00
Total: 4,950.00
Currency: USD
"""


def llm_payload(**overrides) -> dict:
    payload = {name: {"value": None, "confidence": 0.0} for name in HEADER_FIELDS}
    payload.update(overrides)
    payload.setdefault("line_items", [])
    return payload


def test_heuristics_extract_every_supported_field():
    found = extraction.heuristic_pass(INVOICE_TEXT)

    assert found["invoice_number"].value == "INV-2026-0042"
    assert found["invoice_date"].value == "2026-10-05"
    assert found["subtotal"].value == "4,500.00"
    assert found["tax"].value == "450.00"
    assert found["total"].value == "4,950.00"
    assert found["currency"].value == "USD"
    assert all(field.source == "heuristic" for field in found.values())
    assert all(field.confidence == 0.75 for field in found.values())
    assert found["total"].source_span == {"matched": "Total: 4,950.00"}


def test_heuristics_ignore_a_bare_invoice_heading():
    found = extraction.heuristic_pass("INVOICE\nThank you for your business\n")
    assert "invoice_number" not in found


def test_heuristics_require_a_digit_in_the_invoice_number():
    found = extraction.heuristic_pass("Invoice Number: REFUND\n")
    assert "invoice_number" not in found


def test_heuristics_do_not_confuse_subtotal_with_total():
    found = extraction.heuristic_pass("Subtotal: 10.00\nTotal: 11.00\n")
    assert found["subtotal"].value == "10.00"
    assert found["total"].value == "11.00"


def test_heuristic_values_win_over_the_llm(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: llm_payload(
            total={"value": 999.0, "confidence": 0.99},
            supplier_name={"value": "Acme Supplies Ltd", "confidence": 0.8},
        ),
    )

    result = extraction.extract(INVOICE_TEXT)

    assert money_to_float(result.total.value) == 4950.0
    assert result.total.source == "heuristic"
    assert result.supplier_name.value == "Acme Supplies Ltd"
    assert result.supplier_name.source == "llm"


def test_llm_fills_only_the_gaps(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: llm_payload(
            supplier_name={"value": "Gamma Ltd", "confidence": 0.82},
            customer_name={"value": "Northwind", "confidence": 0.77},
        ),
    )

    result = extraction.extract("Total: 100.00\nCurrency: EUR\n")

    assert result.supplier_name.value == "Gamma Ltd"
    assert result.customer_name.value == "Northwind"
    assert float(result.total.value) == 100.0
    assert result.currency.value == "EUR"


def test_absent_values_stay_null_with_zero_confidence(monkeypatch):
    monkeypatch.setattr(extraction, "complete_json", lambda system, user: llm_payload())

    result = extraction.extract("Nothing useful here at all")

    for name in HEADER_FIELDS:
        entry = getattr(result, name)
        assert entry.value is None
        assert entry.confidence == 0.0
    assert result.document_confidence == 0.0


def test_llm_values_are_normalized_by_the_contract(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: llm_payload(
            invoice_date={"value": "October 5, 2026", "confidence": 0.9},
            subtotal={"value": "$1,200.50", "confidence": 0.9},
            line_items=[
                {
                    "description": "Widget",
                    "quantity": "2",
                    "unit_price": "$10.00",
                    "amount": "20.00",
                    "confidence": 0.8,
                }
            ],
        ),
    )

    result = extraction.extract("Amount due: 1,200.50")

    assert result.invoice_date.value == "2026-10-05"
    assert result.subtotal.value == 1200.5
    assert len(result.line_items) == 1
    assert result.line_items[0].amount == 20.0


def test_llm_money_not_present_in_the_text_is_discarded(monkeypatch):
    """OCR can drop the totals block; the model must not fill the gap."""
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: llm_payload(
            subtotal={"value": 960.0, "confidence": 0.8},
            tax={"value": 21.56, "confidence": 0.9},
            total={"value": 981.56, "confidence": 0.8},
        ),
    )

    result = extraction.extract("Taxable 345.00\nTax rate 6.250%\nTax due 21.56\nOther")

    assert result.subtotal.value is None
    assert result.total.value is None
    assert result.tax.value == 21.56  # this one is in the text
    assert result.subtotal.confidence == 0.0
    assert result.total.confidence == 0.0


def test_llm_money_is_grounded_across_formatting(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: llm_payload(
            subtotal={"value": 1284.0, "confidence": 0.9},
            total={"value": 1284.0, "confidence": 0.9},
        ),
    )

    result = extraction.extract("Amounts: 1,284.00 and 1284")

    assert result.subtotal.value == 1284.0
    assert result.total.value == 1284.0
    assert result.subtotal.source == "llm"


def test_document_confidence_averages_only_present_fields(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: llm_payload(
            supplier_name={"value": "Acme", "confidence": 0.8},
        ),
    )

    result = extraction.extract("Total: 100.00\n")

    # heuristic total (0.75) + llm supplier (0.8) -> mean 0.775
    assert result.document_confidence == pytest.approx(0.775)


def test_malformed_llm_output_triggers_one_repair_retry(monkeypatch):
    calls: list[str] = []

    def flaky(system: str, user: str) -> dict:
        calls.append(user)
        if len(calls) == 1:
            raise ValueError("not json")
        return llm_payload(supplier_name={"value": "Acme", "confidence": 0.8})

    monkeypatch.setattr(extraction, "complete_json", flaky)

    result = extraction.extract("Total: 100.00")

    assert len(calls) == 2
    assert "not valid per the schema" in calls[1]
    assert result.supplier_name.value == "Acme"


def test_unrepairable_llm_output_raises(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "complete_json",
        lambda system, user: (_ for _ in ()).throw(ValueError("still broken")),
    )

    with pytest.raises(ValueError, match="still broken"):
        extraction.extract("Total: 100.00")


def test_structured_columns_are_sent_to_the_llm(monkeypatch):
    seen: list[str] = []

    def capture(system: str, user: str) -> dict:
        seen.append(user)
        return llm_payload()

    monkeypatch.setattr(extraction, "complete_json", capture)

    extraction.extract("a: 1", structured_columns=["Invoice Number", "Total"])

    assert "Spreadsheet columns: ['Invoice Number', 'Total']" in seen[0]


def test_duplicate_key_is_stable_and_requires_both_fields():
    complete = ExtractionOut.model_validate(
        {
            "supplier_name": {"value": "Acme"},
            "invoice_number": {"value": "INV-1"},
        }
    )
    expected = hashlib.sha256(b"Acme||INV-1").hexdigest()
    assert extraction.heuristic_conflict_key(complete) == expected

    incomplete = ExtractionOut.model_validate({"invoice_number": {"value": "INV-1"}})
    assert extraction.heuristic_conflict_key(incomplete) is None
