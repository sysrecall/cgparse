"""Parser tests: CSV/XLSX quirks, digital vs scanned PDFs, OCR routing."""

import io

import pandas as pd
import pytest

from app.queues import parsers


def _xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(pages: list[str]) -> bytes:
    import fitz

    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    data = document.tobytes()
    document.close()
    return data


def test_parse_csv_builds_label_value_rows():
    data = b"Invoice Number,Supplier,Total\nINV-1,Acme,100.00\n"
    chunks = parsers.parse_csv(data, "invoice.csv")

    assert len(chunks) == 1
    assert chunks[0]["chunk_type"] == "row"
    assert chunks[0]["page_number"] is None
    assert chunks[0]["content"] == "Invoice Number: INV-1; Supplier: Acme; Total: 100.00"
    assert chunks[0]["meta"]["row"] == 1
    assert chunks[0]["meta"]["columns"] == ["Invoice Number", "Supplier", "Total"]


def test_parse_csv_skips_empty_cells_and_bad_lines():
    data = b"a,b,c\n1,,3\n4,5,6,7\n8,9,10\n"
    chunks = parsers.parse_csv(data, "rows.csv")

    contents = [c["content"] for c in chunks]
    assert contents == ["a: 1; c: 3", "a: 8; b: 9; c: 10"]


def test_parse_csv_keeps_unicode():
    data = "Supplier,City\nCafé Müller,Zürich\n".encode()
    chunks = parsers.parse_csv(data, "unicode.csv")
    assert "Café Müller" in chunks[0]["content"]


def test_parse_csv_rejects_empty_input():
    with pytest.raises(pd.errors.EmptyDataError):
        parsers.parse_csv(b"", "empty.csv")


def test_parse_csv_labels_a_second_table_after_a_preamble():
    data = (
        b"Invoice Number,Supplier,Subtotal,Total\n"
        b"INV-1,Acme,100.00,110.00\n"
        b"Item,Qty,Amount\n"
        b"Widget,2,50.00\n"
    )
    chunks = parsers.parse_csv(data, "preamble.csv")

    assert [c["content"] for c in chunks] == [
        "Invoice Number: INV-1; Supplier: Acme; Subtotal: 100.00; Total: 110.00",
        "Item: Widget; Qty: 2; Amount: 50.00",
    ]
    assert chunks[1]["meta"]["columns"] == ["Item", "Qty", "Amount"]


def test_parse_xlsx_reads_every_sheet():
    data = _xlsx_bytes(
        {
            "Invoice": [["Invoice Number", "Total"], ["INV-1", "100.00"]],
            "Notes": [["Note"], ["Thank you"]],
        }
    )
    chunks = parsers.parse_xlsx(data, "book.xlsx")

    assert {c["meta"]["sheet"] for c in chunks} == {"Invoice", "Notes"}
    invoice = next(c for c in chunks if c["meta"]["sheet"] == "Invoice")
    assert invoice["content"] == "Invoice Number: INV-1; Total: 100.00"
    assert invoice["meta"]["columns"] == ["Invoice Number", "Total"]


def test_parse_xlsx_skips_empty_rows():
    data = _xlsx_bytes({"Sheet1": [["a", "b"], [1, None], [None, None], [2, 3]]})
    chunks = parsers.parse_xlsx(data, "rows.xlsx")
    assert [c["content"] for c in chunks] == ["a: 1", "a: 2; b: 3"]


def test_parse_xlsx_combines_a_key_value_preamble_into_one_chunk():
    data = _xlsx_bytes(
        {
            "Invoice": [
                ["Invoice Number", "INV-1", None, None],
                ["Supplier", "Acme", None, None],
                [None, None, None, None],
                ["Item", "Qty", "Unit Price", "Amount"],
                ["Steel brackets", 200, 3.5, 700],
            ]
        }
    )
    chunks = parsers.parse_xlsx(data, "mixed.xlsx")

    # The preamble collapses to one chunk (detached "Supplier: Acme" lines embed
    # poorly), and the buried item header is found so the row is labelled right.
    assert [c["content"] for c in chunks] == [
        "Invoice Number: INV-1; Supplier: Acme",
        "Item: Steel brackets; Qty: 200; Unit Price: 3.5; Amount: 700",
    ]
    assert chunks[0]["meta"]["columns"] is None
    assert chunks[1]["meta"]["columns"] == ["Item", "Qty", "Unit Price", "Amount"]


def test_parse_pdf_digital_returns_one_chunk_per_page():
    data = _pdf_bytes(["Page one invoice text", "Page two continuation"])
    chunks = parsers.parse_pdf_digital(data, "doc.pdf")

    assert [c["page_number"] for c in chunks] == [1, 2]
    assert all(c["chunk_type"] == "page" for c in chunks)
    assert "Page one" in chunks[0]["content"]
    assert chunks[0]["meta"]["width"] > 0


def test_has_text_layer_detects_digital_blank_and_corrupt_pdfs():
    assert parsers.has_text_layer(_pdf_bytes(["A real digital text layer on page one"]))
    assert not parsers.has_text_layer(_pdf_bytes([""]))
    assert not parsers.has_text_layer(b"%PDF-1.4\nthis is not a real pdf")


def test_parse_via_ocr_normalizes_pages(monkeypatch):
    monkeypatch.setattr(
        parsers,
        "openparser_parse",
        lambda data, filename: {
            "pages": [
                {"page_number": 1, "text": "first", "confidence": 0.91},
                {"page_number": 2, "text": "second", "confidence": None},
            ]
        },
    )
    chunks = parsers.parse_via_ocr(b"image-bytes", "scan.png")

    assert [c["page_number"] for c in chunks] == [1, 2]
    assert chunks[0]["meta"]["ocr_confidence"] == 0.91
    assert chunks[1]["meta"]["ocr_confidence"] is None


def test_parse_any_routes_by_source_kind(monkeypatch):
    csv_chunks, csv_parser = parsers.parse_any("csv", b"a,b\n1,2\n", "x.csv", "text/csv")
    assert csv_parser == "csv"
    assert csv_chunks[0]["chunk_type"] == "row"

    xlsx = _xlsx_bytes({"S": [["a"], [1]]})
    _, xlsx_parser = parsers.parse_any("spreadsheet", xlsx, "x.xlsx", "application/vnd.ms-excel")
    assert xlsx_parser == "xlsx"

    monkeypatch.setattr(
        parsers,
        "openparser_parse",
        lambda data, filename: {"pages": [{"page_number": 1, "text": "ocr", "confidence": 0.8}]},
    )
    image_chunks, image_parser = parsers.parse_any("image", b"img", "x.png", "image/png")
    assert image_parser == "openparser"
    assert image_chunks[0]["content"] == "ocr"

    # A PDF without a text layer must go through OCR too.
    scanned = _pdf_bytes([""])
    _, pdf_parser = parsers.parse_any("pdf", scanned, "scan.pdf", "application/pdf")
    assert pdf_parser == "openparser"


def test_parse_any_rejects_unknown_source_kind():
    with pytest.raises(ValueError, match="no parser"):
        parsers.parse_any("tiff", b"", "x.tiff", "image/tiff")


def test_parse_pdf_digital_rejects_corrupt_bytes():
    from pdfplumber.utils.exceptions import PdfminerException

    with pytest.raises(PdfminerException):
        parsers.parse_pdf_digital(b"%PDF-1.4\nnot a pdf", "broken.pdf")
