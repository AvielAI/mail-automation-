"""PDF and image text extraction using PyMuPDF + pdfplumber, with OCR fallback."""
from __future__ import annotations

import io
import logging
from typing import Optional

from app.models.entities import ExtractedDoc

logger = logging.getLogger(__name__)


def extract_from_bytes(
    raw_bytes: bytes,
    mime_type: str,
    filename: str,
    message_id: str = "",
    attachment_id: str = "",
) -> ExtractedDoc:
    """Entry point: dispatch to PDF or image extractor based on MIME type."""
    doc = ExtractedDoc(
        message_id=message_id,
        attachment_id=attachment_id,
        source="pdf",
    )

    if mime_type == "application/pdf":
        text, pages, warnings = _extract_pdf(raw_bytes, filename)
        doc.raw_text = text
        doc.page_count = pages
        doc.extraction_warnings = warnings
    elif mime_type.startswith("image/"):
        text, warnings = _extract_image(raw_bytes, filename)
        doc.raw_text = text
        doc.source = "ocr"
        doc.extraction_warnings = warnings
    else:
        doc.extraction_warnings = [f"Unsupported MIME type: {mime_type}"]

    return doc


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _extract_pdf(raw_bytes: bytes, filename: str) -> tuple[str, int, list[str]]:
    """Try PyMuPDF first, then pdfplumber; OCR if text is sparse."""
    warnings: list[str] = []
    text = ""
    page_count = 0

    # -- PyMuPDF
    try:
        text, page_count = _pymupdf_extract(raw_bytes)
    except Exception as exc:
        warnings.append(f"PyMuPDF failed: {exc}")

    # -- pdfplumber fallback / supplement
    # Catch BaseException: pdfplumber's Rust/cffi deps can raise PanicException
    if not text.strip():
        try:
            text2, pc2 = _pdfplumber_extract(raw_bytes)
            if text2.strip():
                text = text2
                page_count = pc2
        except BaseException as exc:
            warnings.append(f"pdfplumber failed: {type(exc).__name__}: {exc}")

    # -- OCR fallback if text still sparse (scanned PDF)
    if len(text.strip()) < 50:
        warnings.append("Text sparse; attempting OCR on PDF pages")
        try:
            ocr_text = _ocr_pdf_bytes(raw_bytes)
            if ocr_text.strip():
                text = ocr_text
                warnings.append("OCR used for PDF")
        except Exception as exc:
            warnings.append(f"OCR fallback failed: {exc}")

    return text, page_count, warnings


def _pymupdf_extract(raw_bytes: bytes) -> tuple[str, int]:
    import fitz  # PyMuPDF
    parts: list[str] = []
    with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
        page_count = doc.page_count
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts), page_count


def _pdfplumber_extract(raw_bytes: bytes) -> tuple[str, int]:
    import pdfplumber
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts), page_count


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

def _extract_image(raw_bytes: bytes, filename: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from app.services.extraction.ocr_extractor import ocr_image_bytes
        text = ocr_image_bytes(raw_bytes)
        return text, warnings
    except Exception as exc:
        warnings.append(f"Image OCR failed: {exc}")
        return "", warnings


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _ocr_pdf_bytes(raw_bytes: bytes) -> str:
    """Convert PDF pages to images and OCR each page."""
    try:
        from app.services.extraction.ocr_extractor import ocr_pdf_bytes
        return ocr_pdf_bytes(raw_bytes)
    except Exception as exc:
        raise RuntimeError(f"OCR PDF failed: {exc}") from exc
