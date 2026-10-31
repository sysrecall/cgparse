"""Validation rule engine — six rules, each persisted with severity + message.

Aggregate status: any error -> needs_review; all clear -> validated.
(This service never sets 'failed' — failure is reserved for pipeline crashes.)
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app_core.models.enums import Severity
from app_core.models.extraction import Extraction
from app_core.models.validation_result import ValidationResult
from app_core.schemas.extraction import money_to_float
from sqlalchemy import select
from sqlalchemy.orm import Session

TOLERANCE = Decimal("0.01")

REQUIRED_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                   "subtotal", "tax", "total", "currency")


@dataclass
class RuleResult:
    rule_id: str
    severity: Severity
    message: str
    field: str | None = None


def _field_value(fields: dict, name: str) -> object:
    entry = fields.get(name) or {}
    return entry.get("value")


def _dec(value: object) -> Decimal | None:
    # Heuristic money values are literal strings ("$4,500.00"); run them through
    # the same coercion the extraction contract uses so commas/symbols are fine.
    if isinstance(value, Decimal):
        return value
    parsed = money_to_float(value)
    return Decimal(str(parsed)) if parsed is not None else None


def rule_missing_fields(fields: dict) -> list[RuleResult]:
    return [
        RuleResult("missing_field", Severity.ERROR, f"required field '{name}' is missing", field=name)
        for name in REQUIRED_FIELDS
        if _field_value(fields, name) in (None, "")
    ]


def rule_format(fields: dict) -> list[RuleResult]:
    results = []
    date_value = _field_value(fields, "invoice_date")
    if date_value is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(date_value)):
        results.append(RuleResult("type_and_format", Severity.ERROR,
                                  f"invoice_date '{date_value}' is not ISO-8601", field="invoice_date"))
    for name in ("subtotal", "tax", "total"):
        value = _field_value(fields, name)
        if value is not None and _dec(value) is None:
            results.append(RuleResult("type_and_format", Severity.ERROR,
                                      f"{name} '{value}' is not numeric", field=name))
    return results


def rule_line_items_sum(fields: dict, line_items: list) -> list[RuleResult]:
    subtotal = _dec(_field_value(fields, "subtotal"))
    if subtotal is None or not line_items:
        return []
    total_items = sum((_dec(item.amount) or Decimal(0)) for item in line_items)
    if abs(total_items - subtotal) > TOLERANCE:
        return [RuleResult(
            "line_items_sum", Severity.ERROR,
            f"line items sum to {total_items} but subtotal is {subtotal}",
            field="line_items",
        )]
    return []


def rule_subtotal_tax_total(fields: dict) -> list[RuleResult]:
    subtotal, tax, total = (_dec(_field_value(fields, n)) for n in ("subtotal", "tax", "total"))
    if None in (subtotal, tax, total):
        return []
    assert subtotal is not None and tax is not None and total is not None
    if abs(subtotal + tax - total) > TOLERANCE:
        return [RuleResult(
            "subtotal_tax_total", Severity.ERROR,
            f"subtotal ({subtotal}) + tax ({tax}) != total ({total})",
            field="total",
        )]
    return []


def rule_negative_values(line_items: list) -> list[RuleResult]:
    results = []
    for i, item in enumerate(line_items, start=1):
        for attr in ("quantity", "unit_price", "amount"):
            value = _dec(getattr(item, attr, None))
            if value is not None and value < 0:
                results.append(RuleResult(
                    "negative_or_impossible_values", Severity.ERROR,
                    f"line item {i}: {attr} is negative ({value})", field="line_items",
                ))
    return results


def rule_duplicate(extraction: Extraction, session: Session) -> list[RuleResult]:
    key_supplier = _field_value(extraction.fields, "supplier_name")
    key_number = _field_value(extraction.fields, "invoice_number")
    if not key_supplier or not key_number:
        return []
    duplicates = session.execute(
        select(Extraction.id)
        .where(
            Extraction.document_id != extraction.document_id,
            Extraction.fields["invoice_number"]["value"].astext == str(key_number),
            Extraction.fields["supplier_name"]["value"].astext == str(key_supplier),
        )
        .limit(1)
    ).scalar_one_or_none()
    if duplicates:
        return [RuleResult(
            "duplicate_invoice", Severity.WARNING,
            f"same supplier+invoice_number already ingested (extraction {duplicates})",
            field="invoice_number",
        )]
    return []


def run_all(extraction: Extraction, session: Session) -> tuple[list[ValidationResult], str]:
    """Returns (rows_to_insert, aggregate_status)."""
    fields = extraction.fields
    line_items = list(extraction.line_items)

    found: list[RuleResult] = []
    found += rule_missing_fields(fields)
    found += rule_format(fields)
    found += rule_line_items_sum(fields, line_items)
    found += rule_subtotal_tax_total(fields)
    found += rule_negative_values(line_items)
    found += rule_duplicate(extraction, session)

    rows = [
        ValidationResult(
            extraction_id=extraction.id,
            rule_id=r.rule_id,
            severity=r.severity.value,
            message=r.message,
            field=r.field,
        )
        for r in found
    ]
    status = "needs_review" if any(r.severity == Severity.ERROR for r in found) else "validated"
    return rows, status
