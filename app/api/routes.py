"""FastAPI routes for the dashboard and API."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from io import BytesIO
from pathlib import Path

from app.core.config import Config
from app.core.database import get_db
from app.services.export_service import export_to_excel, export_to_word
from app.services.pipeline import process_message

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ─── Dashboard Pages ─────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard - job list page."""
    with get_db() as db:
        jobs = db.execute(
            "SELECT * FROM jobs ORDER BY capture_date DESC LIMIT 100"
        ).fetchall()
        stats = {
            "total": db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            "submitted": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_status = 'submitted'"
            ).fetchone()[0],
            "sent": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_status = 'sent'"
            ).fetchone()[0],
            "blocked": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_status = 'blocked'"
            ).fetchone()[0],
            "review": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_status = 'review_needed'"
            ).fetchone()[0],
            "pending": db.execute(
                "SELECT COUNT(*) FROM jobs WHERE submission_status = 'pending'"
            ).fetchone()[0],
        }
        # WhatsApp status and scheduling info
        whatsapp_status = db.execute(
            "SELECT value FROM settings WHERE key = 'whatsapp_status'"
        ).fetchone()
        last_poll = db.execute(
            "SELECT value FROM settings WHERE key = 'last_poll_time'"
        ).fetchone()
        next_poll = db.execute(
            "SELECT value FROM settings WHERE key = 'next_poll_time'"
        ).fetchone()
        first_run_done = db.execute(
            "SELECT value FROM settings WHERE key = 'first_run_completed'"
        ).fetchone()
        last_cycle_count = db.execute(
            "SELECT value FROM settings WHERE key = 'last_cycle_new_count'"
        ).fetchone()
        total_messages = db.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
        historical_count = db.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE is_historical = 1"
        ).fetchone()[0]

    scheduling_info = {
        "last_poll_time": last_poll[0] if last_poll else "N/A",
        "next_poll_time": next_poll[0] if next_poll else "N/A",
        "first_run_completed": (first_run_done[0] == "true") if first_run_done else False,
        "last_cycle_new_count": int(last_cycle_count[0]) if last_cycle_count else 0,
        "total_messages": total_messages,
        "historical_messages": historical_count,
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "jobs": [dict(j) for j in jobs],
        "stats": stats,
        "whatsapp_status": whatsapp_status[0] if whatsapp_status else "unknown",
        "mode": Config.get().mode,
        "scheduling": scheduling_info,
    })


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    """Job detail page."""
    with get_db() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return HTMLResponse("<h1>Job not found</h1>", status_code=404)

        form_answers = db.execute(
            "SELECT * FROM form_answers WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall()
        runs = db.execute(
            "SELECT * FROM job_runs WHERE job_id = ? ORDER BY started_at DESC", (job_id,)
        ).fetchall()
        errors = db.execute(
            "SELECT * FROM errors WHERE job_id = ? ORDER BY created_at DESC", (job_id,)
        ).fetchall()
        files = db.execute(
            "SELECT * FROM generated_files WHERE job_id = ?", (job_id,)
        ).fetchall()

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": dict(job),
        "form_answers": [dict(f) for f in form_answers],
        "runs": [dict(r) for r in runs],
        "errors": [dict(e) for e in errors],
        "files": [dict(f) for f in files],
    })


@router.get("/blocked", response_class=HTMLResponse)
async def blocked_jobs(request: Request):
    """Blocked jobs page."""
    with get_db() as db:
        jobs = db.execute(
            "SELECT * FROM jobs WHERE submission_status IN ('blocked', 'email_failed', 'review_needed') "
            "ORDER BY capture_date DESC"
        ).fetchall()
    return templates.TemplateResponse("blocked.html", {
        "request": request,
        "jobs": [dict(j) for j in jobs],
    })


@router.get("/sent", response_class=HTMLResponse)
async def sent_jobs(request: Request):
    """Sent/submitted jobs page."""
    with get_db() as db:
        jobs = db.execute(
            "SELECT * FROM jobs WHERE submission_status IN ('sent', 'submitted') "
            "ORDER BY sent_date DESC"
        ).fetchall()
    return templates.TemplateResponse("sent.html", {
        "request": request,
        "jobs": [dict(j) for j in jobs],
    })


# ─── API Endpoints ───────────────────────────────────────────

@router.get("/api/jobs")
async def api_list_jobs(
    status: Optional[str] = None,
    group: Optional[str] = None,
    limit: int = Query(default=50, le=500),
):
    """API: List jobs with optional filters."""
    query = "SELECT * FROM jobs"
    params = []
    conditions = []

    if status:
        conditions.append("submission_status = ?")
        params.append(status)
    if group:
        conditions.append("whatsapp_group = ?")
        params.append(group)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY capture_date DESC LIMIT ?"
    params.append(limit)

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/jobs/{job_id}")
async def api_get_job(job_id: int):
    """API: Get single job details."""
    with get_db() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        form_answers = db.execute(
            "SELECT * FROM form_answers WHERE job_id = ?", (job_id,)
        ).fetchall()
        runs = db.execute(
            "SELECT * FROM job_runs WHERE job_id = ?", (job_id,)
        ).fetchall()
    return {
        "job": dict(job),
        "form_answers": [dict(f) for f in form_answers],
        "runs": [dict(r) for r in runs],
    }


@router.post("/api/jobs/{job_id}/retry")
async def api_retry_job(job_id: int):
    """API: Retry a blocked/failed job."""
    with get_db() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)

        # Re-process the job message
        message = {
            "id": job["raw_message_id"],
            "text": job["raw_message"],
            "group": job["whatsapp_group"],
        }
        db.execute(
            "UPDATE jobs SET submission_status = 'retrying' WHERE id = ?", (job_id,)
        )

    result = await process_message(message)
    return result


@router.post("/api/jobs/{job_id}/approve")
async def api_approve_job(job_id: int):
    """API: Approve a job in review queue for processing."""
    with get_db() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)

        message = {
            "id": job["raw_message_id"],
            "text": job["raw_message"],
            "group": job["whatsapp_group"],
        }
        # Force high confidence for approved jobs
        db.execute(
            "UPDATE jobs SET detection_confidence = 95, submission_status = 'processing' WHERE id = ?",
            (job_id,),
        )

    result = await process_message(message)
    return result


@router.post("/api/process-text")
async def api_process_text(request: Request):
    """API: Process a raw text message manually (for testing)."""
    body = await request.json()
    text = body.get("text", "")
    group = body.get("group", "Manual Input")

    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)

    message = {"text": text, "group": group, "id": None}
    result = await process_message(message)
    return result


# ─── Export Endpoints ────────────────────────────────────────

@router.get("/api/export/excel")
async def api_export_excel(
    status: Optional[str] = None,
    group: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """Export jobs to Excel."""
    filters = {}
    if status:
        filters["status"] = status
    if group:
        filters["group"] = group
    if from_date:
        filters["from_date"] = from_date
    if to_date:
        filters["to_date"] = to_date

    data = export_to_excel(filters or None)
    filename = f"jobs_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/export/word")
async def api_export_word(
    status: Optional[str] = None,
    group: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """Export jobs to Word report."""
    filters = {}
    if status:
        filters["status"] = status
    if group:
        filters["group"] = group
    if from_date:
        filters["from_date"] = from_date
    if to_date:
        filters["to_date"] = to_date

    data = export_to_word(filters or None)
    filename = f"jobs_report_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"

    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── Status Endpoints ────────────────────────────────────────

@router.get("/api/status")
async def api_status():
    """API: System status with scheduling info."""
    config = Config.get()
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        whatsapp_status = db.execute(
            "SELECT value FROM settings WHERE key = 'whatsapp_status'"
        ).fetchone()
        last_message = db.execute(
            "SELECT captured_at FROM raw_messages ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        last_poll = db.execute(
            "SELECT value FROM settings WHERE key = 'last_poll_time'"
        ).fetchone()
        next_poll = db.execute(
            "SELECT value FROM settings WHERE key = 'next_poll_time'"
        ).fetchone()
        first_run = db.execute(
            "SELECT value FROM settings WHERE key = 'first_run_completed'"
        ).fetchone()
        last_cycle = db.execute(
            "SELECT value FROM settings WHERE key = 'last_cycle_new_count'"
        ).fetchone()
        total_msgs = db.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
        historical = db.execute("SELECT COUNT(*) FROM raw_messages WHERE is_historical = 1").fetchone()[0]

    return {
        "mode": config.mode,
        "whatsapp_status": whatsapp_status[0] if whatsapp_status else "not_started",
        "total_jobs": total,
        "total_messages": total_msgs,
        "historical_messages": historical,
        "last_message_at": last_message[0] if last_message else None,
        "last_poll_time": last_poll[0] if last_poll else None,
        "next_poll_time": next_poll[0] if next_poll else None,
        "first_run_completed": (first_run[0] == "true") if first_run else False,
        "last_cycle_new_count": int(last_cycle[0]) if last_cycle else 0,
        "scheduling_settings": config.scheduling,
        "monitored_groups": config.whatsapp_groups,
    }
