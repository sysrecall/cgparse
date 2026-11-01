"""OpenParser hosted-OCR provider — the only OCR engine for v1.

The model is configurable (``PROC_OPENPARSER_MODEL``); PaddleOCR-VL is the
default because the evaluation corpus was measured with it. Normalizes whatever
the SDK returns into our PageParse shape:
    {"pages": [{"page_number": int, "text": str, "confidence": float | None}]}
"""

import re
import tempfile
from collections import defaultdict
from pathlib import Path

from app_core.settings import get_processing_settings

DEFAULT_OCR_MODEL = "paddleocr-vl-1.6"

# Extensions OpenParser accepts directly (PDF/PNG/JPEG)
SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}


class OpenParserError(RuntimeError):
    pass


def parse_document(data: bytes, filename: str) -> dict:
    """Blocking call; for long PDFs the SDK may return a job — we follow it."""
    from openparser import OpenParserClient

    settings = get_processing_settings()
    if not settings.openparser_api_key:
        raise OpenParserError("OPENPARSER_API_KEY is not configured")

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise OpenParserError(f"OpenParser accepts PDF/PNG/JPEG only, got {suffix!r}")

    client = OpenParserClient(api_key=settings.openparser_api_key)
    model = (settings.openparser_model or "").strip() or DEFAULT_OCR_MODEL
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        result = client.parse.sync({"ocr_model": model}, file=Path(tmp.name))

    # Sync wait expired -> SDK returns a durable job reference; poll it.
    if not _has_pages(result) and getattr(result, "id", None):
        result = client.wait_for_job(result.id)

    if not _has_pages(result):
        raise OpenParserError(f"unexpected OpenParser response: {result!r:.200}")

    return _normalize(result)


def _has_pages(result: object) -> bool:
    return bool(getattr(result, "pages", None) or getattr(result, "elements", None) or getattr(result, "text", None))


def _normalize(result: object) -> dict:
    pages: dict[int, dict] = defaultdict(lambda: {"page_number": 0, "text": [], "confidence": []})

    for element in getattr(result, "elements", None) or []:
        text = _element_text(element)
        if not text:
            continue
        conf = getattr(getattr(element, "confidence", None), "score", None)
        locations = getattr(element, "locations", None) or []
        if locations:
            page_no = getattr(locations[0], "page_number", 1) or 1
        else:
            page_no = 1
        pages[page_no]["page_number"] = page_no
        pages[page_no]["text"].append(text)
        if conf is not None:
            pages[page_no]["confidence"].append(conf)

    if not pages and getattr(result, "text", None):
        pages[1] = {"page_number": 1, "text": [result.text], "confidence": []}

    out = []
    for page_no in sorted(pages):
        p = pages[page_no]
        confs = p["confidence"]
        out.append(
            {
                "page_number": page_no,
                "text": "\n".join(p["text"]),
                "confidence": round(sum(confs) / len(confs), 4) if confs else None,
            }
        )
    return {"pages": out}


def _element_text(element: object) -> str:
    """Text for one layout block.

    PaddleOCR-VL returns tables as ``kind="table"`` blocks with an **empty**
    ``text``: the content lives in ``cells`` (and a duplicate ``html``). Reading
    only ``text`` therefore dropped every table -- which on an invoice is the
    line items *and* the totals block, so extraction saw a document with no
    amounts. Rebuild the table as rows so the text and the LLM both see it.
    """
    text = getattr(element, "text", None)
    if text:
        return text
    if getattr(element, "kind", None) == "table":
        return _table_text(element)
    return ""


def _table_text(element: object) -> str:
    cells = getattr(element, "cells", None) or []
    rows: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for cell in cells:
        value = (getattr(cell, "text", None) or "").strip()
        if not value:
            continue
        row = getattr(cell, "row_index", 0) or 0
        column = getattr(cell, "column_index", 0) or 0
        rows[row].append((column, value))

    if rows:
        return "\n".join(" | ".join(value for _, value in sorted(rows[row])) for row in sorted(rows))

    # No structured cells: fall back to the HTML the provider also returns.
    html = getattr(element, "html", None)
    return _strip_html(html) if html else ""


def _strip_html(html: str) -> str:
    """Flatten a table's HTML into one row per <tr> and one cell per <td>."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.DOTALL | re.IGNORECASE)
    if not rows:
        return re.sub(r"<[^>]+>", " ", html).strip()
    lines = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.DOTALL | re.IGNORECASE)
        values = [re.sub(r"<[^>]+>", " ", cell).strip() for cell in cells]
        values = [re.sub(r"\s+", " ", value) for value in values if value]
        if values:
            lines.append(" | ".join(values))
    return "\n".join(lines)

