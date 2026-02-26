"""Flask application factory."""
from __future__ import annotations

import logging
import os

from flask import Flask
from dotenv import load_dotenv

from .config import Config, ensure_dirs
from .services.storage.base import Storage
from .utils.helpers import setup_logging

load_dotenv()


def create_app(config_class: type = Config) -> Flask:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    logger = logging.getLogger(__name__)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_class)

    # Ensure data directories exist
    ensure_dirs(config_class)

    # Session config
    app.secret_key = config_class.SECRET_KEY
    app.config["SESSION_COOKIE_SECURE"] = config_class.SESSION_COOKIE_SECURE
    app.config["SESSION_COOKIE_SAMESITE"] = config_class.SESSION_COOKIE_SAMESITE
    app.config["SESSION_COOKIE_HTTPONLY"] = config_class.SESSION_COOKIE_HTTPONLY
    app.config["PERMANENT_SESSION_LIFETIME"] = config_class.PERMANENT_SESSION_LIFETIME

    # Storage singleton — attached to app context
    app.storage = Storage(config_class.DATA_DIR)  # type: ignore[attr-defined]

    # Register blueprints
    from .routes.main import bp as main_bp
    from .routes.auth import bp as auth_bp
    from .routes.sync import bp as sync_bp
    from .routes.export import bp as export_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(sync_bp, url_prefix="/sync")
    app.register_blueprint(export_bp, url_prefix="/export")

    logger.info(
        "App created | DATA_DIR=%s STORAGE_MODE=%s",
        config_class.DATA_DIR,
        config_class.STORAGE_MODE,
    )
    return app


# ---------------------------------------------------------------------------
# Module-level app instance — required for Render's auto-detected
# "gunicorn app:app" start command which cannot be overridden on Free tier.
# Guarded so test-time imports (which lack google-auth's cffi deps) don't fail.
# ---------------------------------------------------------------------------
import sys as _sys
if "pytest" not in _sys.modules:
    app = create_app()
