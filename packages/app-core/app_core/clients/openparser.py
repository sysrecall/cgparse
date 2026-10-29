"""OpenParser (hosted PaddleOCR-VL) provider — the sole OCR engine for v1.

Normalizes whatever the SDK returns into our PageParse shape:
    {"pages": [{"page_number": int, "text": str, "confidence": float | None}]}
"""

import tempfile
from collections import defaultdict
from pathlib import Path

from app_core.settings import get_processing_settings

OCR_MODEL = "paddleocr-vl-1.6"

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
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        result = client.parse.sync({"ocr_model": OCR_MODEL}, file=Path(tmp.name))

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
        text = getattr(element, "text", None)
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
