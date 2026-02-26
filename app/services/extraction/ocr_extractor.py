"""OCR extraction — pytesseract + pdf2image with graceful degradation."""
from __future__ import annotations

import io
import logging
from typing import Optional

from app.config import Config

logger = logging.getLogger(__name__)

# Check availability at module load time
_TESSERACT_AVAILABLE: Optional[bool] = None
_PDF2IMAGE_AVAILABLE: Optional[bool] = None


def _check_tesseract() -> bool:
    global _TESSERACT_AVAILABLE
    if _TESSERACT_AVAILABLE is not None:
        return _TESSERACT_AVAILABLE
    if not Config.OCR_ENABLED:
        _TESSERACT_AVAILABLE = False
        return False
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        _TESSERACT_AVAILABLE = True
    except Exception:
        _TESSERACT_AVAILABLE = False
        logger.warning("Tesseract not available — OCR disabled")
    return _TESSERACT_AVAILABLE


def _check_pdf2image() -> bool:
    global _PDF2IMAGE_AVAILABLE
    if _PDF2IMAGE_AVAILABLE is not None:
        return _PDF2IMAGE_AVAILABLE
    try:
        import pdf2image  # noqa: F401
        _PDF2IMAGE_AVAILABLE = True
    except ImportError:
        _PDF2IMAGE_AVAILABLE = False
    return _PDF2IMAGE_AVAILABLE


def ocr_image_bytes(raw_bytes: bytes, lang: str = "heb+eng") -> str:
    """OCR a single image given as raw bytes."""
    if not _check_tesseract():
        raise RuntimeError("Tesseract not available")
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(raw_bytes))
    return pytesseract.image_to_string(img, lang=lang)


def ocr_pdf_bytes(raw_bytes: bytes, lang: str = "heb+eng", dpi: int = 200) -> str:
    """Convert PDF to images and OCR each page."""
    if not _check_tesseract():
        raise RuntimeError("Tesseract not available")
    if not _check_pdf2image():
        raise RuntimeError("pdf2image not available")

    import pytesseract
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(raw_bytes, dpi=dpi)
    parts: list[str] = []
    for img in images:
        try:
            parts.append(pytesseract.image_to_string(img, lang=lang))
        except Exception as exc:
            logger.warning("OCR page error: %s", exc)
    return "\n".join(parts)


def tesseract_available() -> bool:
    return _check_tesseract()
