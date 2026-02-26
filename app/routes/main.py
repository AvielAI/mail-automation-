"""Main / dashboard routes."""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, render_template, request, session

from app.config import Config

bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    storage: "Storage" = current_app.storage  # type: ignore[attr-defined]
    connected = "gmail_credentials" in session
    last_run = storage.sync_log.last()
    record_count = storage.records.count()
    review_count = len(storage.records.needs_review())
    error_count = len(storage.errors.recent(500))
    return render_template(
        "dashboard.html",
        connected=connected,
        last_run=last_run,
        record_count=record_count,
        review_count=review_count,
        error_count=error_count,
        storage_mode=Config.STORAGE_MODE,
        data_dir=str(Config.DATA_DIR),
    )


@bp.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@bp.route("/records")
def records():
    storage = current_app.storage  # type: ignore[attr-defined]
    ins_type = request.args.get("type", "")
    all_records = storage.records.all()
    if ins_type:
        all_records = [r for r in all_records if r.insurance_type == ins_type]
    return render_template("records.html", records=all_records, filter_type=ins_type)


@bp.route("/review")
def review():
    storage = current_app.storage  # type: ignore[attr-defined]
    records = storage.records.needs_review()
    return render_template("review.html", records=records)


@bp.route("/errors")
def errors():
    storage = current_app.storage  # type: ignore[attr-defined]
    errors = storage.errors.recent(100)
    logs = storage.store.load_log_lines(tail=200)
    return render_template("errors.html", errors=errors, logs=logs)
