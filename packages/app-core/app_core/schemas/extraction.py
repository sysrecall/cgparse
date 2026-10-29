"""Extraction output contract — the shape every producer (heuristic or LLM) must emit.

Anti-hallucination contract enforced here:
- unknown field -> value=None, confidence=0.0 (never a guess)
- dates normalized to ISO-8601 or rejected to None
- numerics parsed from money strings ("$4,500.00" -> 4500.0) or rejected to None
"""

import re
from datetime import date

from dateutil import parser as dateparser
from pydantic import BaseModel, Field, field_validator


class FieldOut(BaseModel):
    value: str | float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_span: dict | None = None


class LineItemOut(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def _to_number(cls, v: object) -> float | None:
        return _money_to_float(v)


class ExtractionOut(BaseModel):
    invoice_number: FieldOut = FieldOut()
    invoice_date: FieldOut = FieldOut()
    supplier_name: FieldOut = FieldOut()
    customer_name: FieldOut = FieldOut()
    subtotal: FieldOut = FieldOut()
    tax: FieldOut = FieldOut()
    total: FieldOut = FieldOut()
    currency: FieldOut = FieldOut()
    line_items: list[LineItemOut] = []
    document_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("invoice_date", mode="before")
    @classmethod
    def _normalize_date(cls, v: object) -> object:
        if isinstance(v, dict) and v.get("value"):
            parsed = _date_to_iso(v["value"])
            if parsed is None:
                # Unparseable date -> do not invent; drop to null per the contract
                return {**v, "value": None, "confidence": 0.0}
            return {**v, "value": parsed}
        return v

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def _normalize_money(cls, v: object) -> object:
        if isinstance(v, dict) and v.get("value") is not None:
            parsed = _money_to_float(v["value"])
            if parsed is None:
                return {**v, "value": None, "confidence": 0.0}
            return {**v, "value": parsed}
        return v


_MONEY_RE = re.compile(r"[^\d.\-]")


def _money_to_float(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    cleaned = _MONEY_RE.sub("", str(v).strip())
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else None
    except ValueError:
        return None


def _date_to_iso(v: object) -> str | None:
    if v is None:
        return None
    try:
        parsed = dateparser.parse(str(v), dayfirst=False, yearfirst=False)
        if isinstance(parsed, date):
            return parsed.isoformat()[:10]
    except (ValueError, OverflowError):
        pass
    return None
