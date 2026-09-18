"""Secure document text extraction for JD/resume ingestion."""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("backend-api.brain.documents")

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 100_000
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".text"}


class DocumentIngestError(ValueError):
    """Raised when an uploaded document cannot be accepted or parsed."""


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    content_type: str
    filename: str
    page_count: int | None
    warnings: list[str]


def _extension(filename: str) -> str:
    name = (filename or "").strip().lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def _sniff_kind(data: bytes, filename: str, content_type: str | None) -> str:
    ext = _extension(filename)
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if data.startswith(b"%PDF") or ext == ".pdf" or ctype == "application/pdf":
        return "pdf"
    if (
        data[:2] == b"PK"
        and (ext == ".docx" or "wordprocessingml" in ctype or ctype.endswith("docx"))
    ):
        return "docx"
    if ext in {".txt", ".md", ".text"} or ctype.startswith("text/"):
        return "text"
    if data.startswith(b"%PDF"):
        return "pdf"
    raise DocumentIngestError(
        "Unsupported document type. Upload PDF, DOCX, or plain text."
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentIngestError("Could not decode text document")


def _extract_pdf(data: bytes) -> tuple[str, int, list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentIngestError("PDF support is not installed") from exc
    warnings: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentIngestError("PDF could not be read") from exc
    if getattr(reader, "is_encrypted", False):
        raise DocumentIngestError("Encrypted PDFs are not supported")
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append((page.extract_text() or "").strip())
        except Exception:
            warnings.append("One or more PDF pages could not be parsed")
    text = "\n\n".join(part for part in pages if part)
    if len(re.sub(r"\s+", "", text)) < 40:
        raise DocumentIngestError(
            "PDF contained little or no extractable text. "
            "Scanned resumes need OCR (not enabled yet) — paste text instead."
        )
    return text, len(reader.pages), warnings


def _extract_docx(data: bytes) -> tuple[str, None, list[str]]:
    try:
        from docx import Document
    except ImportError as exc:
        raise DocumentIngestError("DOCX support is not installed") from exc
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentIngestError("DOCX could not be read") from exc
    parts = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    if len(re.sub(r"\s+", "", text)) < 20:
        raise DocumentIngestError("DOCX contained little or no extractable text")
    return text, None, []


def extract_document_text(
    *,
    data: bytes,
    filename: str,
    content_type: str | None = None,
) -> ExtractedDocument:
    if not data:
        raise DocumentIngestError("Empty upload")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentIngestError(
            f"Document exceeds {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB limit"
        )
    # Reject embedded NUL / obvious binary junk for text path later.
    kind = _sniff_kind(data, filename, content_type)
    warnings: list[str] = []
    page_count: int | None = None
    if kind == "pdf":
        text, page_count, warnings = _extract_pdf(data)
    elif kind == "docx":
        text, page_count, warnings = _extract_docx(data)
    else:
        text = _decode_text(data)
    text = text.replace("\x00", "").strip()
    if not text:
        raise DocumentIngestError("No text could be extracted")
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS]
        warnings.append("Extracted text was truncated to the maximum length")
    return ExtractedDocument(
        text=text,
        content_type=kind,
        filename=(filename or "upload").strip()[:255] or "upload",
        page_count=page_count,
        warnings=warnings,
    )
