"""PDF validation and text extraction.

Uploads are validated by content, not by the declared filename or MIME type: the bytes must start
with a PDF header, parse as a PDF, be unencrypted, and stay within the page limit. Text extraction
is best effort and never raises: scanned or image-only PDFs simply yield no text.
"""

import io
import logging
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
ACCEPTED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
MAX_EXTRACTION_PAGES = 10
MAX_TEXT_CHARACTERS = 100_000


class InvalidPdf(ValueError):
    """The upload is not an acceptable PDF. The message is safe to show to users."""


@dataclass(frozen=True)
class ExtractedText:
    text: str
    page_count: int
    pages_scanned: int
    truncated: bool


def safe_filename(name: str | None) -> str:
    """Basename only, no control or path characters, ending in .pdf, at most 255 characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f\"]", "", base).strip().strip(".") or "resume.pdf"
    if not base.lower().endswith(".pdf"):
        raise InvalidPdf("Only PDF files are accepted (the file name must end in .pdf).")
    return base[-255:]


def check_declared_type(content_type: str | None) -> None:
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared and declared not in ACCEPTED_CONTENT_TYPES:
        raise InvalidPdf("Only PDF files are accepted.")


def open_pdf(data: bytes, *, max_pages: int) -> PdfReader:
    """Validate PDF content and return a reader. Raises InvalidPdf with a user-facing reason."""
    if not data:
        raise InvalidPdf("The file is empty.")
    # A PDF header must appear at the start (some generators prepend a few bytes; allow 1 KB).
    if PDF_MAGIC not in data[:1024]:
        raise InvalidPdf("The file is not a PDF (its content does not start with a PDF header).")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise InvalidPdf("Password-protected PDFs are not supported. Remove the password and upload again.")
        page_count = len(reader.pages)
    except InvalidPdf:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError, OSError) as exc:
        raise InvalidPdf("The PDF is damaged or malformed and could not be read.") from exc
    if page_count == 0:
        raise InvalidPdf("The PDF has no pages.")
    if page_count > max_pages:
        raise InvalidPdf(f"The PDF has {page_count} pages; resumes are limited to {max_pages}.")
    return reader


def extract_text(reader: PdfReader) -> ExtractedText:
    """Extract text from the first pages. Pages that fail are skipped; never raises for page errors."""
    page_count = len(reader.pages)
    parts: list[str] = []
    total = 0
    truncated = page_count > MAX_EXTRACTION_PAGES
    scanned = 0
    for page in reader.pages[:MAX_EXTRACTION_PAGES]:
        scanned += 1
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # pypdf raises many types for odd content streams; skip the page.
            logger.info("Skipped an unreadable PDF page during resume extraction (%s)", type(exc).__name__)
            continue
        if total + len(text) > MAX_TEXT_CHARACTERS:
            text = text[: MAX_TEXT_CHARACTERS - total]
            truncated = True
        parts.append(text)
        total += len(text)
        if total >= MAX_TEXT_CHARACTERS:
            break
    return ExtractedText(text="\n".join(parts), page_count=page_count, pages_scanned=scanned, truncated=truncated)
