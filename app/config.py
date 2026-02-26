"""Application configuration — loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path


class Config:
    # ------------------------------------------------------------------ Flask
    SECRET_KEY: str = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    FLASK_ENV: str = os.environ.get("FLASK_ENV", "production")

    # ---------------------------------------------------------------- Storage
    DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "/tmp/insurance_data"))
    STORAGE_MODE: str = os.environ.get("STORAGE_MODE", "ephemeral")  # ephemeral | persistent

    # Derived sub-directories (resolved lazily in create_app)
    STATE_DIR: Path = DATA_DIR / "state"
    ATTACHMENTS_DIR: Path = DATA_DIR / "attachments"
    EXTRACTED_DIR: Path = DATA_DIR / "extracted_text"
    EXPORTS_DIR: Path = DATA_DIR / "exports"

    # ----------------------------------------------------------------- Google
    GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_OAUTH_SCOPES: list[str] = os.environ.get(
        "GOOGLE_OAUTH_SCOPES",
        "https://www.googleapis.com/auth/gmail.readonly",
    ).split()

    GOOGLE_REDIRECT_URI: str = os.environ.get(
        "GOOGLE_REDIRECT_URI", ""
    )  # auto-derived if empty

    # ----------------------------------------------------------------- Gmail
    GMAIL_SEARCH_QUERY: str = os.environ.get(
        "GMAIL_SEARCH_QUERY",
        (
            "subject:(ביטוח OR insurance OR פוליסה OR policy OR חידוש OR renewal"
            " OR פרמיה OR premium OR \"דמי ביטוח\" OR \"מספר פוליסה\")"
            " OR"
            " (ביטוח OR insurance OR פוליסה OR policy)"
        ),
    )
    GMAIL_MAX_RESULTS: int = int(os.environ.get("GMAIL_MAX_RESULTS", "500"))

    # -------------------------------------------------------------------- OCR
    OCR_ENABLED: bool = os.environ.get("OCR_ENABLED", "true").lower() == "true"

    # --------------------------------------------------------------- Sessions
    SESSION_COOKIE_SECURE: bool = (
        os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    )
    SESSION_COOKIE_SAMESITE: str = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_HTTPONLY: bool = True
    PERMANENT_SESSION_LIFETIME: int = 3600 * 8  # 8 hours


def ensure_dirs(cfg: type[Config]) -> None:
    """Create all DATA_DIR sub-directories, tolerating failures on ephemeral FS."""
    for d in [
        cfg.DATA_DIR,
        cfg.STATE_DIR,
        cfg.ATTACHMENTS_DIR,
        cfg.EXTRACTED_DIR,
        cfg.EXPORTS_DIR,
    ]:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # ephemeral or read-only — will error later on write
