# Re-use the module-level Flask instance created in app/__init__.py.
# This serves both "gunicorn wsgi:app" (explicit) and avoids a second
# create_app() call when the app package has already been initialised.
from app import app  # noqa: F401

__all__ = ["app"]
