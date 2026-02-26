"""Gmail OAuth2 routes."""
from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Config

bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

# Allow HTTP for local dev
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "0")


def _redirect_uri() -> str:
    if Config.GOOGLE_REDIRECT_URI:
        return Config.GOOGLE_REDIRECT_URI
    return url_for("auth.callback", _external=True)


def _make_flow() -> Flow:
    client_config = {
        "web": {
            "client_id": Config.GOOGLE_CLIENT_ID,
            "client_secret": Config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri()],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=Config.GOOGLE_OAUTH_SCOPES,
        redirect_uri=_redirect_uri(),
    )
    return flow


@bp.route("/connect")
def connect():
    """Initiate OAuth2 flow."""
    if not Config.GOOGLE_CLIENT_ID or not Config.GOOGLE_CLIENT_SECRET:
        return (
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars are not set.",
            500,
        )
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    logger.info("OAuth2 flow started")
    return redirect(auth_url)


@bp.route("/callback")
def callback():
    """Handle OAuth2 callback."""
    if "error" in request.args:
        logger.warning("OAuth error: %s", request.args["error"])
        return redirect(url_for("main.index") + "?error=oauth_denied")

    state = session.pop("oauth_state", None)
    if not state or state != request.args.get("state"):
        logger.warning("OAuth state mismatch")
        return redirect(url_for("main.index") + "?error=state_mismatch")

    flow = _make_flow()
    flow.fetch_token(authorization_response=request.url)
    creds: Credentials = flow.credentials

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }

    # Persist to file store
    storage = current_app.storage  # type: ignore[attr-defined]
    storage.store.save_oauth_token(token_data)

    # Also keep in session (for fast checks)
    session["gmail_credentials"] = token_data
    session.permanent = True

    logger.info("Gmail connected successfully")
    return redirect(url_for("main.index") + "?connected=1")


@bp.route("/disconnect")
def disconnect():
    storage = current_app.storage  # type: ignore[attr-defined]
    storage.store.delete_oauth_token()
    session.pop("gmail_credentials", None)
    logger.info("Gmail disconnected")
    return redirect(url_for("main.index") + "?disconnected=1")


@bp.route("/status")
def status():
    connected = "gmail_credentials" in session
    return jsonify({"connected": connected})


def load_credentials_from_store(storage) -> Credentials | None:
    """Load stored credentials, refreshing if expired."""
    # Try session first
    cred_data = session.get("gmail_credentials")
    if not cred_data:
        # Try file store (e.g. after server restart)
        cred_data = storage.store.load_oauth_token()
        if cred_data:
            session["gmail_credentials"] = cred_data
            session.permanent = True

    if not cred_data:
        return None

    from datetime import datetime
    expiry = None
    if cred_data.get("expiry"):
        try:
            expiry = datetime.fromisoformat(cred_data["expiry"])
        except ValueError:
            expiry = None

    creds = Credentials(
        token=cred_data.get("token"),
        refresh_token=cred_data.get("refresh_token"),
        token_uri=cred_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=cred_data.get("client_id", Config.GOOGLE_CLIENT_ID),
        client_secret=cred_data.get("client_secret", Config.GOOGLE_CLIENT_SECRET),
        scopes=cred_data.get("scopes", Config.GOOGLE_OAUTH_SCOPES),
        expiry=expiry,
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            import google.auth.transport.requests as tr
            creds.refresh(tr.Request())
            updated = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or []),
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
            }
            storage.store.save_oauth_token(updated)
            session["gmail_credentials"] = updated
        except Exception as exc:
            logger.error("Token refresh failed: %s", exc)
            return None

    return creds
