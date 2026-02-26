"""Misc utility helpers."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mask_id_number(value: str) -> str:
    """Mask ID number — show only last 4 digits."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 4:
        return "****"
    return "*" * (len(digits) - 4) + digits[-4:]


def parse_date(raw: str) -> Optional[str]:
    """Try common date formats; return ISO date string or empty string."""
    if not raw:
        return ""
    raw = raw.strip()
    formats = [
        "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d",
        "%d-%m-%Y", "%d/%m/%y", "%d.%m.%y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw  # return as-is if unparseable


def safe_float(val: str) -> Optional[float]:
    """Convert string to float, handling commas and Hebrew chars."""
    if not val:
        return None
    cleaned = re.sub(r"[^\d.]", "", val.replace(",", "."))
    try:
        return float(cleaned)
    except ValueError:
        return None


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
