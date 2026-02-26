"""Export routes — generate and download Excel workbook."""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, render_template, send_file

bp = Blueprint("export", __name__)
logger = logging.getLogger(__name__)


@bp.route("/", methods=["GET"])
def export_page():
    storage = current_app.storage  # type: ignore[attr-defined]
    record_count = storage.records.count()
    review_count = len(storage.records.needs_review())
    excel_exists = storage.store.excel_export_path.exists()
    return render_template(
        "export.html",
        record_count=record_count,
        review_count=review_count,
        excel_exists=excel_exists,
    )


@bp.route("/download")
def download():
    storage = current_app.storage  # type: ignore[attr-defined]
    records = storage.records.all()
    sync_runs = storage.sync_log.all()
    errors = storage.errors.all()

    from app.services.excel_export_service import build_workbook
    wb = build_workbook(records, sync_runs, errors)

    export_path = storage.store.excel_export_path
    try:
        wb.save(str(export_path))
    except OSError as exc:
        logger.warning("Could not cache Excel to disk: %s", exc)
        # Serve from memory
        import io
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name="insurance_tracker.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return send_file(
        str(export_path),
        as_attachment=True,
        download_name="insurance_tracker.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
