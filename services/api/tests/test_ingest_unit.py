"""Ingest helpers that do not need a database: magic sniffing, names, limits."""

import base64
import io
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.services import ingest

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
CSV = b"Invoice Number,Total\nINV-1,100.00\n"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
XLSX = b"PK\x03\x04" + b"\x00" * 120
EXE = b"MZ" + b"\x00" * 120


def test_safe_filename_strips_paths_and_specials():
    assert ingest.safe_filename("../../etc/passwd") == "passwd"
    assert ingest.safe_filename("C:\\Users\\me\\invoice final (1).pdf") == "invoice_final__1_.pdf"
    assert ingest.safe_filename("") == "upload"


@pytest.mark.parametrize(
    ("head", "filename", "expected_mime", "expected_kind"),
    [
        (CSV, "invoice.csv", "text/csv", "csv"),
        (PDF, "invoice.pdf", "application/pdf", "pdf"),
        (PNG, "scan.png", "image/png", "image"),
        (
            XLSX,
            "book.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "spreadsheet",
        ),
    ],
)
def test_sniff_detects_supported_types(head, filename, expected_mime, expected_kind):
    mime, kind = ingest.sniff(head, filename)
    assert mime == expected_mime
    assert kind == expected_kind


def test_sniff_rejects_executables_and_unknown_types():
    with pytest.raises(ingest.UnsupportedFile):
        ingest.sniff(EXE, "malware.pdf")
    with pytest.raises(ingest.UnsupportedFile):
        ingest.sniff(b"plain text", "notes.txt")


@pytest.mark.asyncio
async def test_empty_upload_is_rejected_before_any_io():
    upload = UploadFile(file=io.BytesIO(b""), filename="empty.csv")
    result = await ingest.ingest_one(upload, session=None)
    assert result.error == "empty file"


@pytest.mark.asyncio
async def test_unsupported_upload_is_reported_per_file():
    upload = UploadFile(file=io.BytesIO(EXE), filename="setup.exe")
    result = await ingest.ingest_one(upload, session=None)
    assert "unsupported file type" in result.error


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected(monkeypatch):
    monkeypatch.setattr(
        ingest,
        "get_api_settings",
        lambda: SimpleNamespace(max_upload_mb=0),
    )
    upload = UploadFile(file=io.BytesIO(CSV), filename="invoice.csv")

    result = await ingest.ingest_one(upload, session=None)

    assert result.error == "file exceeds 0 MB limit"
