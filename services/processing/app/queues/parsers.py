"""Parsers: one function per input type, all returning the same normalized shape.

    [{"chunk_type": "page"|"row", "page_number": int|None, "content": str, "meta": dict}]

CSV/XLSX produce one chunk per data row (chunk_type="row", page_number=None).
PDF/image produce one chunk per page (chunk_type="page").
"""

import io

import pandas as pd
import pdfplumber
from app_core.clients.openparser import parse_document as openparser_parse


def _has_digit(value: str) -> bool:
    return any(ch.isdigit() for ch in value)


def _normalize_grid(rows: list[list]) -> list[list[str]]:
    """Stringify, trim, and drop trailing empty cells from every row."""
    grid: list[list[str]] = []
    for row in rows:
        cells = [("" if cell is None else str(cell)).strip() for cell in row]
        end = len(cells)
        while end and not cells[end - 1]:
            end -= 1
        grid.append(cells[:end])
    return grid


def _row_chunk(sheet: str | None, row: int, content: str, columns: list[str] | None) -> dict:
    return {
        "chunk_type": "row",
        "page_number": None,
        "content": content,
        "meta": {"row": row, "sheet": sheet, "columns": columns},
    }


def _grid_to_chunks(grid: list[list], sheet: str | None) -> list[dict]:
    """Turn one raw sheet grid into search chunks.

    Real spreadsheets are not always a clean header table: many put a key/value
    preamble above the item table (``Invoice Number | INV-1``). Reading every
    file as "row 1 is the header" then mislabels each line with the wrong column
    names -- the values survive, but the chunk text that both the search index
    and the LLM see is wrong (``Invoice Number: Steel brackets``).

    So we walk the grid and classify rows:
      * a run of >=2 rows of exactly two cells whose first is a non-numeric
        label is a key/value block -> ``label: value``;
      * a row of >=2 cells that are all non-numeric becomes the active header;
      * everything else is a data row, emitted as ``header: value`` pairs.
    """
    rows = _normalize_grid(grid)
    chunks: list[dict] = []
    headers: list[tuple[int, str]] | None = None
    header_width = 0
    emitted = 0
    index = 0
    while index < len(rows):
        row = rows[index]
        if not any(row):
            index += 1
            continue
        cells = [(position, value) for position, value in enumerate(row) if value]

        # Key/value preamble: consecutive two-cell rows with a non-numeric label.
        # Two such rows can also be a tiny two-column table (header + one data
        # row), so require more evidence: either a longer run, or a value that
        # carries a digit -- which a column header never would.
        if len(cells) == 2 and not _has_digit(cells[0][1]):
            end = index
            while end < len(rows):
                probe = [(p, v) for p, v in enumerate(rows[end]) if v]
                if len(probe) != 2 or _has_digit(probe[0][1]):
                    break
                end += 1
            if end - index >= 2 and (end - index >= 3 or _has_digit(cells[1][1])):
                # One chunk, not one per line: "Currency: EUR" on its own is a
                # three-word chunk whose embedding drifts toward unrelated
                # queries, so detached header lines pollute semantic results.
                pairs = []
                for key_row in rows[index:end]:
                    values = [value for value in key_row if value]
                    pairs.append(f"{values[0]}: {values[1]}")
                emitted += 1
                chunks.append(_row_chunk(sheet, emitted, "; ".join(pairs), None))
                index = end
                continue

        # A header row: several cells, none of them holding a number. A row of
        # the same width as the active header is data, not a new header.
        if (
            len(cells) >= 2
            and not any(_has_digit(value) for _, value in cells)
            and (headers is None or len(row) != header_width)
        ):
            headers = cells
            header_width = len(row)
            index += 1
            continue

        if headers is not None:
            pairs = [
                f"{name}: {row[position]}"
                for position, name in headers
                if position < len(row) and row[position]
            ]
            if pairs:
                emitted += 1
                chunks.append(
                    _row_chunk(sheet, emitted, "; ".join(pairs), [name for _, name in headers])
                )
        else:
            emitted += 1
            chunks.append(_row_chunk(sheet, emitted, "; ".join(value for value in row if value), None))
        index += 1
    return chunks


def parse_csv(data: bytes, filename: str) -> list[dict]:
    frame = pd.read_csv(
        io.BytesIO(data), header=None, dtype=str, keep_default_na=False, on_bad_lines="skip"
    )
    return _grid_to_chunks(frame.values.tolist(), None)


def parse_xlsx(data: bytes, filename: str) -> list[dict]:
    # keep_default_na=False: an empty cell is "", not the literal string "nan".
    book = pd.read_excel(
        io.BytesIO(data),
        header=None,
        sheet_name=None,
        dtype=str,
        engine="openpyxl",
        keep_default_na=False,
    )
    chunks: list[dict] = []
    for sheet_name, frame in book.items():
        chunks.extend(_grid_to_chunks(frame.values.tolist(), str(sheet_name)))
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
    """Scanned PDF / image -> hosted OCR via OpenParser (PROC_OPENPARSER_MODEL)."""
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
