"""Extraction: deterministic heuristics first, LLM second; heuristics win on conflict."""

import hashlib
import re

from app_core.clients.llm import complete_json
from app_core.schemas.extraction import ExtractionOut, FieldOut, money_to_float

# Regex heuristics tolerate , : ; | tab separators between label and value.
# NOTE: alternation order matters (longest-first), and money/total patterns need
# word boundaries so "Subtotal" doesn't match the "total" rule.
HEURISTICS: dict[str, re.Pattern[str]] = {
    "invoice_number": re.compile(
        r"(?i)\binvoice\s*(?:(?:number|num|no\.?|#)\s*[:#]?\s*|[:#]\s*)"
        r"([A-Za-z0-9][A-Za-z0-9/_-]{2,})"
    ),
    "invoice_date": re.compile(
        r"(?i)(?:invoice\s*)?date\s*(?:of\s*issue)?\s*[,:\t|]\s*([0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})"
    ),
    "subtotal": re.compile(r"(?i)\bsub\s*total\b\s*[,:\t|]?\s*\$?\s*([0-9][\d,]*\.\d{2})"),
    "tax": re.compile(r"(?i)(?:^|\b)(?:sales\s+)?tax(?:\s*(?:amount|vat))?\b\s*[,:\t|]?\s*\$?\s*([0-9][\d,]*\.\d{2})"),
    "total": re.compile(r"(?i)\btotal(?:\s*(?:amount|due|payable))?\b\s*[,:\t|]?\s*\$?\s*([0-9][\d,]*\.\d{2})"),
    "currency": re.compile(r"\b(USD|EUR|GBP|INR|JPY|CAD|AUD|CHF|CNY)\b"),
}

MONEY_FIELDS = {"subtotal", "tax", "total"}
DATE_FIELDS = {"invoice_date"}

LLM_SYSTEM = (
    "You are an invoice-data extraction engine. Extract fields from the document text "
    "into EXACTLY this JSON shape (no extra keys, no commentary):\n"
    '{"invoice_number": {"value": str|null, "confidence": 0.0-1.0}, '
    '"invoice_date": {"value": "YYYY-MM-DD"|null, "confidence": 0.0-1.0}, '
    '"supplier_name": {"value": str|null, "confidence": 0.0-1.0}, '
    '"customer_name": {"value": str|null, "confidence": 0.0-1.0}, '
    '"subtotal": {"value": number|null, "confidence": 0.0-1.0}, '
    '"tax": {"value": number|null, "confidence": 0.0-1.0}, '
    '"total": {"value": number|null, "confidence": 0.0-1.0}, '
    '"currency": {"value": str|null, "confidence": 0.0-1.0}, '
    '"line_items": [{"description": str|null, "quantity": number|null, '
    '"unit_price": number|null, "amount": number|null, "confidence": 0.0-1.0}]}\n'
    "RULES: Use ONLY what appears in the text. If a value is absent or unreadable, "
    "use null with confidence 0. NEVER guess or invent values. Numbers are plain "
    "floats without currency symbols or thousands separators. "
    "Line items are the rows describing goods/services (description, quantity, "
    "unit price, amount) — extract every such row you find, even when the input is "
    "flat 'label: value' text rather than a table."
)


def heuristic_pass(text: str) -> dict[str, FieldOut]:
    found: dict[str, FieldOut] = {}
    for field, pattern in HEURISTICS.items():
        # Scan every match, not just the first: headings like "INVOICE" would
        # otherwise shadow the real "Invoice Number: INV-..." line.
        for match in pattern.finditer(text):
            value = match.group(1)
            if field == "invoice_number" and not re.search(r"\d", value):
                continue  # a bare word is not an invoice number
            found[field] = FieldOut(
                value=value, confidence=0.75, source_span={"matched": match.group(0)}, source="heuristic"
            )
            break
    return found


def heuristic_conflict_key(extraction: ExtractionOut) -> str | None:
    """Duplicate-detection key: sha256(supplier || invoice_number)."""
    supplier = extraction.supplier_name.value
    number = extraction.invoice_number.value
    if not supplier or not number:
        return None
    return hashlib.sha256(f"{supplier}||{number}".encode()).hexdigest()


_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _money_tokens(text: str) -> set[str]:
    """Every numeric token in the source, normalized to two decimals.

    Used to check that an LLM-supplied amount is actually present in the text.
    Comparing normalized forms (not raw strings) keeps ``$1,284.00`` and
    ``1284`` equivalent.
    """
    tokens: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        value = money_to_float(match.group(0))
        if value is not None:
            tokens.add(f"{value:.2f}")
    return tokens


def _money_is_grounded(value: object, tokens: set[str]) -> bool:
    parsed = money_to_float(value)
    return parsed is not None and f"{parsed:.2f}" in tokens


def extract(text: str, structured_columns: list[str] | None = None) -> ExtractionOut:
    """Two-pass extraction on the document text.

    Pass 1 (always): regex heuristics — deterministic, free, with match spans.
    Pass 2 (LLM): fills what heuristics missed; heuristic values win on conflict.
    For structured spreadsheets the column names themselves are evidence and are
    passed to the LLM as context.
    """
    heuristics = heuristic_pass(text)

    llm = _llm_pass(text, structured_columns)
    money_tokens = _money_tokens(text)

    merged: dict[str, FieldOut] = {}
    for field in ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                  "subtotal", "tax", "total", "currency"):
        heuristic = heuristics.get(field)
        llm_field = getattr(llm, field, FieldOut())
        if heuristic is not None and heuristic.value is not None:
            merged[field] = heuristic  # boxed evidence beats generation
        elif llm_field.value is not None:
            # Money must appear in the source. An OCR pass that drops the totals
            # block otherwise lets the model fill the gap with a plausible number,
            # which is worse than null: it looks confident and it is wrong.
            if field in MONEY_FIELDS and not _money_is_grounded(llm_field.value, money_tokens):
                merged[field] = FieldOut()
            else:
                llm_field.source = "llm"
                merged[field] = llm_field
        else:
            merged[field] = FieldOut()  # explicit null + 0.0 — never invented

    extraction = ExtractionOut(**merged, line_items=llm.line_items)

    confidences = [v.confidence for v in merged.values() if v.value is not None]
    extraction.document_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    return extraction


def _llm_pass(text: str, structured_columns: list[str] | None) -> ExtractionOut:
    user_parts = []
    if structured_columns:
        user_parts.append(f"Spreadsheet columns: {structured_columns}")
    user_parts.append(f"Document text:\n{text[:12000]}")
    user = "\n\n".join(user_parts)
    try:
        return ExtractionOut.model_validate(complete_json(LLM_SYSTEM, user))
    except Exception:  # noqa: BLE001 — covers both malformed JSON and schema violations
        # Repair retry with the strict schema reminder
        raw = complete_json(
            LLM_SYSTEM,
            user + "\n\nYour previous answer was not valid per the schema. Return ONLY the JSON object.",
        )
        return ExtractionOut.model_validate(raw)
