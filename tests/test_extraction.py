"""Tests for PDF/OCR extraction layer."""
import io
import pytest

from app.models.entities import ExtractedDoc
from app.services.extraction.pdf_extractor import extract_from_bytes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_pdf() -> bytes:
    """Return a minimal but structurally valid PDF bytes stub."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000058 00000 n\n"
        b"0000000115 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )


@pytest.fixture(autouse=True)
def mock_pdfplumber(monkeypatch):
    """Prevent pdfplumber from being imported (broken cffi in test env).
    Replace with a stub that raises ImportError so the fallback path is skipped."""
    import app.services.extraction.pdf_extractor as mod

    def _failing_pdfplumber(raw_bytes):
        raise ImportError("pdfplumber mocked out in tests")

    monkeypatch.setattr(mod, "_pdfplumber_extract", _failing_pdfplumber)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_extract_pdf_returns_extracted_doc():
    pdf_bytes = _make_minimal_pdf()
    doc = extract_from_bytes(
        pdf_bytes,
        mime_type="application/pdf",
        filename="test.pdf",
        message_id="msg1",
        attachment_id="att1",
    )
    assert isinstance(doc, ExtractedDoc)
    assert doc.source == "pdf"
    assert doc.message_id == "msg1"
    assert doc.attachment_id == "att1"
    assert isinstance(doc.extraction_warnings, list)


def test_extract_pdf_no_crash_on_empty():
    """Empty bytes should not raise — just return empty text with warnings."""
    doc = extract_from_bytes(
        b"",
        mime_type="application/pdf",
        filename="empty.pdf",
    )
    assert isinstance(doc, ExtractedDoc)
    assert isinstance(doc.extraction_warnings, list)
    assert any(doc.extraction_warnings)


def test_extract_unsupported_mime():
    doc = extract_from_bytes(
        b"some data",
        mime_type="text/csv",
        filename="data.csv",
    )
    assert isinstance(doc, ExtractedDoc)
    assert any("Unsupported" in w for w in doc.extraction_warnings)


def test_extract_image_graceful_without_tesseract(monkeypatch):
    """If OCR unavailable, extraction should degrade gracefully."""
    import app.services.extraction.ocr_extractor as ocr_mod
    monkeypatch.setattr(ocr_mod, "_TESSERACT_AVAILABLE", False)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG bytes
    doc = extract_from_bytes(
        fake_png,
        mime_type="image/png",
        filename="scan.png",
    )
    assert isinstance(doc, ExtractedDoc)
    assert isinstance(doc.raw_text, str)


def test_extract_pdf_with_text_via_pymupdf(monkeypatch):
    """If PyMuPDF returns text, it should be stored in the doc."""
    import app.services.extraction.pdf_extractor as mod

    monkeypatch.setattr(mod, "_pymupdf_extract", lambda _raw: ("Policy Number: 123456", 1))

    doc = extract_from_bytes(
        b"fake pdf bytes",
        mime_type="application/pdf",
        filename="policy.pdf",
        message_id="m1",
    )
    assert doc.raw_text == "Policy Number: 123456"
    assert doc.page_count == 1
