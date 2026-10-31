"""Parsers: one function per input type, all returning the same normalized shape.

    [{"chunk_type": "page"|"row", "page_number": int|None, "content": str, "meta": dict}]

CSV/XLSX produce one chunk per data row (chunk_type="row", page_number=None).
PDF/image produce one chunk per page (chunk_type="page").
"""

import io

import pandas as pd
import pdfplumber
from app_core.clients.openparser import parse_document as openparser_parse


def parse_csv(data: bytes, filename: str) -> list[dict]:
    chunks: list[dict] = []
    df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, on_bad_lines="skip")
    headers = [str(h).strip() for h in df.columns]
    for i, row in enumerate(df.itertuples(index=False), start=1):
        pairs = [f"{h}: {v}" for h, v in zip(headers, row, strict=False) if str(v).strip()]
        if pairs:
            chunks.append(
                {
                    "chunk_type": "row",
                    "page_number": None,
                    "content": "; ".join(pairs),
                    "meta": {"row": i, "sheet": None, "columns": headers},
                }
            )
    return chunks


def parse_xlsx(data: bytes, filename: str) -> list[dict]:
    chunks: list[dict] = []
    # keep_default_na=False: an empty cell is "", not the literal string "nan".
    book = pd.read_excel(
        io.BytesIO(data), sheet_name=None, dtype=str, engine="openpyxl", keep_default_na=False
    )
    for sheet_name, df in book.items():
        headers = [str(h).strip() for h in df.columns]
        for i, row in enumerate(df.itertuples(index=False), start=1):
            pairs = [f"{h}: {v}" for h, v in zip(headers, row, strict=False) if str(v).strip()]
            if pairs:
                chunks.append(
                    {
                        "chunk_type": "row",
                        "page_number": None,
                        "content": "; ".join(pairs),
                        "meta": {"row": i, "sheet": str(sheet_name), "columns": headers},
                    }
                )
    return chunks


def parse_pdf_digital(data: bytes, filename: str) -> list[dict]:
    chunks: list[dict] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            chunks.append(
                {
                    "chunk_type": "page",
                    "page_number": page.page_number,
                    "content": text,
                    "meta": {"width": page.width, "height": page.height},
                }
            )
    return chunks


def parse_via_ocr(data: bytes, filename: str) -> list[dict]:
    """Scanned PDF / image -> hosted PaddleOCR-VL via OpenParser."""
    result = openparser_parse(data, filename)
    return [
        {
            "chunk_type": "page",
            "page_number": p["page_number"],
            "content": p["text"],
            "meta": {"ocr_confidence": p["confidence"]},
        }
        for p in result["pages"]
    ]


def has_text_layer(data: bytes) -> bool:
    """Digital-PDF detection: does the first page carry extractable text?"""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return False
            return len((pdf.pages[0].extract_text() or "").strip()) > 20
    except Exception:  # noqa: BLE001 — any parse failure means "not a digital PDF"
        return False


def parse_any(source_kind: str, data: bytes, filename: str, mime_type: str) -> tuple[list[dict], str]:
    """Router. Returns (chunks, parser_name). Raises on hopeless input."""
    if source_kind == "csv":
        return parse_csv(data, filename), "csv"
    if source_kind == "spreadsheet":
        return parse_xlsx(data, filename), "xlsx"
    if source_kind == "image":
        return parse_via_ocr(data, filename), "openparser"
    if source_kind == "pdf":
        if has_text_layer(data):
            return parse_pdf_digital(data, filename), "pdfplumber"
        return parse_via_ocr(data, filename), "openparser"
    raise ValueError(f"no parser for source_kind={source_kind} mime={mime_type}")
