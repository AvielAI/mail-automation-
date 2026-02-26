"""Sync routes — trigger Gmail scan and processing pipeline."""
from __future__ import annotations

import logging
import threading

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

bp = Blueprint("sync", __name__)
logger = logging.getLogger(__name__)

# Track running sync state per process (ephemeral, fine for single-worker dev)
_sync_state: dict = {"running": False, "run_id": None}
_sync_lock = threading.Lock()


@bp.route("/", methods=["GET"])
def sync_page():
    storage = current_app.storage  # type: ignore[attr-defined]
    last_run = storage.sync_log.last()
    runs = storage.sync_log.all()[-10:]
    return render_template("sync.html", last_run=last_run, runs=runs, sync_state=_sync_state)


@bp.route("/start", methods=["POST"])
def start_sync():
    from app.routes.auth import load_credentials_from_store

    storage = current_app.storage  # type: ignore[attr-defined]
    creds = load_credentials_from_store(storage)
    if not creds:
        return jsonify({"error": "not_connected", "message": "Connect Gmail first"}), 401

    with _sync_lock:
        if _sync_state["running"]:
            return jsonify({"error": "already_running", "run_id": _sync_state["run_id"]}), 409

    custom_query = request.form.get("query", "").strip() or None

    # Run sync in background thread so HTTP request returns immediately
    app = current_app._get_current_object()  # type: ignore[attr-defined]

    def run_sync():
        with _sync_lock:
            _sync_state["running"] = True
        try:
            with app.app_context():
                from app.services.gmail_service import GmailSyncService
                service = GmailSyncService(storage, creds, custom_query=custom_query)
                summary = service.run()
                _sync_state["run_id"] = summary.run_id
        except Exception as exc:
            logger.exception("Sync thread error: %s", exc)
        finally:
            with _sync_lock:
                _sync_state["running"] = False

    t = threading.Thread(target=run_sync, daemon=True)
    t.start()

    return jsonify({"started": True, "message": "Sync started in background"})


@bp.route("/status")
def sync_status():
    storage = current_app.storage  # type: ignore[attr-defined]
    last_run = storage.sync_log.last()
    return jsonify({
        "running": _sync_state["running"],
        "last_run": last_run.to_dict() if last_run else None,
        "record_count": storage.records.count(),
        "review_count": len(storage.records.needs_review()),
    })
