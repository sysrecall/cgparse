"""Ingest pipeline (api side): sniff → hash → stream to Tigris → insert row → enqueue.

Each file runs inside its own SAVEPOINT, so a rejected or failing file rolls back
only its own work — the rest of the batch keeps the rows it already inserted.
"""

import hashlib
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass

import magic
from app_core.clients.storage import delete_object, upload_stream
from app_core.models.document import Document
from app_core.models.enums import DocumentStatus, SourceKind
from app_core.settings import get_api_settings
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CHUNK_SIZE = 1024 * 1024  # 1 MiB
SNIFF_BYTES = 2048

# MIME → source_kind. Magic bytes decide, never the filename.
MIME_TO_KIND: dict[str, SourceKind] = {
    "application/pdf": SourceKind.PDF,
    "image/jpeg": SourceKind.IMAGE,
    "image/png": SourceKind.IMAGE,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": SourceKind.SPREADSHEET,
    "application/vnd.ms-excel": SourceKind.SPREADSHEET,
    "application/x-ole-storage": SourceKind.SPREADSHEET,  # legacy .xls container
    "text/csv": SourceKind.CSV,
    "application/json": SourceKind.CSV,  # some tools label CSV as json; rare but seen
}


DUPLICATE_MESSAGE = "duplicate file (identical checksum already ingested)"


class UnsupportedFile(ValueError):
    pass


class DuplicateFile(ValueError):
    pass


def _discard_upload(storage_key: str | None) -> None:
    """Best-effort cleanup when the database rejects a file we already uploaded."""
    if not storage_key:
        return
    # Cleanup must never mask the real error (or the duplicate we are reporting).
    with suppress(Exception):
        delete_object(storage_key)


@dataclass
class IngestResult:
    filename: str
    document: Document | None = None
    error: str | None = None


def sniff(head: bytes, filename: str) -> tuple[str, SourceKind]:
    mime = magic.from_buffer(head, mime=True)
    if mime in MIME_TO_KIND:
        return mime, MIME_TO_KIND[mime]
    # XLSX/XLSM are ZIP containers — magic sees "application/zip", the extension disambiguates
    if mime == "application/zip" and filename.lower().endswith((".xlsx", ".xlsm")):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", SourceKind.SPREADSHEET
    # Some platforms report CSV as text/plain — fall back to extension.
    if mime in ("text/plain", "application/octet-stream") and filename.lower().endswith(".csv"):
        return "text/csv", SourceKind.CSV
    raise UnsupportedFile(f"unsupported file type: {mime}")


def safe_filename(name: str) -> str:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", base) or "upload"


async def ingest_one(file: UploadFile, session: Session) -> IngestResult:
    """Full per-file path. Any failure is reported per file, never aborts the batch."""
    filename = file.filename or "unnamed"
    storage_key: str | None = None
    try:
        head = await file.read(SNIFF_BYTES)
        if not head:
            return IngestResult(filename, error="empty file")
        mime, kind = sniff(head, filename)

        settings = get_api_settings()
        hasher = hashlib.sha256()
        size = 0
        await file.seek(0)
        while chunk := await file.read(CHUNK_SIZE):
            hasher.update(chunk)
            size += chunk.size if hasattr(chunk, "size") else len(chunk)
            if size > settings.max_upload_mb * 1024 * 1024:
                return IngestResult(filename, error=f"file exceeds {settings.max_upload_mb} MB limit")
        checksum = hasher.hexdigest()

        # One SAVEPOINT per file: a failure below rolls back only this file, so
        # files already accepted in the same batch keep their rows.
        with session.begin_nested():
            duplicate = session.scalar(
                select(Document.id).where(Document.checksum_sha256 == checksum)
            )
            if duplicate is not None:
                # Common case: reject before spending a storage upload.
                raise DuplicateFile(DUPLICATE_MESSAGE)

            await file.seek(0)  # hash pass done — rewind for the storage pass
            doc_id = uuid.uuid4()
            storage_key = f"documents/{doc_id}/original/{safe_filename(filename)}"
            upload_stream(storage_key, file.file, content_type=mime)

            document = Document(
                id=doc_id,
                original_filename=filename,
                checksum_sha256=checksum,
                mime_type=mime,
                source_kind=kind.value,
                storage_key=storage_key,
                size_bytes=size,
                status=DocumentStatus.QUEUED.value,
            )
            session.add(document)
            session.flush()
        return IngestResult(filename, document=document)
    except DuplicateFile as e:
        return IngestResult(filename, error=str(e))
    except UnsupportedFile as e:
        return IngestResult(filename, error=str(e))
    except IntegrityError:
        # Lost a race with a concurrent upload of the same bytes: the unique
        # index is the backstop, and our object is now unreferenced.
        _discard_upload(storage_key)
        return IngestResult(filename, error=DUPLICATE_MESSAGE)
    except Exception as e:  # noqa: BLE001 — per-file isolation is the point
        _discard_upload(storage_key)
        return IngestResult(filename, error=f"{type(e).__name__}: {e}")
