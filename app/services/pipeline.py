"""Main pipeline orchestrator - processes jobs end-to-end in full_automatic mode."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from app.core.config import Config
from app.core.database import get_db
from app.models.job import ExtractedJob, DetectionResult
from app.services.job_classifier import classify_message
from app.services.job_extractor import extract_job_details
from app.services.role_classifier import classify_role
from app.services.resume_generator import generate_resume
from app.services.cover_letter_generator import generate_cover_letter, needs_cover_letter
from app.services.email_sender import send_application_email
from app.services.form_filler import fill_and_submit_form

logger = logging.getLogger(__name__)


def log_run(job_id: int, stage: str, status: str, details: str = ""):
    """Log a pipeline stage run."""
    with get_db() as db:
        db.execute(
            "INSERT INTO job_runs (job_id, stage, status, finished_at, details) VALUES (?, ?, ?, ?, ?)",
            (job_id, stage, status, datetime.now().isoformat(), details),
        )


def log_error(job_id: int | None, stage: str, error: str):
    """Log an error."""
    with get_db() as db:
        db.execute(
            "INSERT INTO errors (job_id, stage, error_type, error_message) VALUES (?, ?, ?, ?)",
            (job_id, stage, "pipeline_error", error),
        )


def create_job_record(job: ExtractedJob, detection: DetectionResult, raw_message_id: int | None = None) -> int:
    """Insert a new job record and return its ID."""
    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO jobs
               (raw_message_id, whatsapp_group, raw_message, job_title, company, location,
                apply_email, apply_link, apply_phone, requirements, description, job_type,
                experience_required, detection_confidence, detection_reason, submission_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing')""",
            (
                raw_message_id, job.whatsapp_group, job.raw_message, job.job_title,
                job.company, job.location, job.apply_email, job.apply_link,
                job.apply_phone, job.requirements, job.description, job.job_type,
                job.experience_required, detection.confidence, detection.reason,
            ),
        )
        return cursor.lastrowid


async def process_message(message: dict) -> dict:
    """Process a single WhatsApp message through the full pipeline.

    Returns a result dict with status and details.
    """
    text = message.get("text", "")
    group = message.get("group", "")
    raw_msg_id = message.get("id")

    result = {
        "message_id": raw_msg_id,
        "group": group,
        "status": "ignored",
        "job_id": None,
        "details": "",
    }

    # Stage 1-2: Job Detection
    detection = classify_message(text)
    logger.info(
        f"Detection: is_job={detection.is_job_post}, actionable={detection.is_actionable}, "
        f"conf={detection.confidence}"
    )

    if not detection.is_actionable and detection.confidence < 50:
        result["status"] = "ignored"
        result["details"] = f"Not actionable (conf={detection.confidence})"
        # Mark message as processed with classification details
        if raw_msg_id:
            with get_db() as db:
                db.execute(
                    """UPDATE raw_messages SET
                        processed = 1, processed_at = ?, classification = 'not_actionable',
                        is_actionable = 0, processing_result = ?
                    WHERE id = ?""",
                    (datetime.now().isoformat(), f"ignored (conf={detection.confidence})", raw_msg_id),
                )
        return result

    # Stage 3: Extract job details
    job = extract_job_details(text, group)
    job.detection_confidence = detection.confidence
    job.detection_reason = detection.reason

    # Create job record
    job_id = create_job_record(job, detection, raw_msg_id)
    result["job_id"] = job_id
    log_run(job_id, "job_extraction", "completed", f"title={job.job_title}, company={job.company}")

    # If borderline confidence (50-79), mark for review
    if detection.confidence < 80:
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET submission_status = 'review_needed' WHERE id = ?",
                (job_id,),
            )
        result["status"] = "review_needed"
        result["details"] = f"Confidence {detection.confidence} - needs review"
        log_run(job_id, "detection", "review_needed", f"conf={detection.confidence}")
        return result

    # Stage 4: Role classification
    role_category, fit_score, profile_name = classify_role(job)
    with get_db() as db:
        db.execute(
            "UPDATE jobs SET role_category = ?, fit_score = ?, selected_application_profile = ? WHERE id = ?",
            (role_category, fit_score, profile_name, job_id),
        )
    log_run(job_id, "role_classification", "completed", f"category={role_category}, fit={fit_score}")

    # Check fit score threshold
    thresholds = Config.get().job_matching.get("matching", {}).get("thresholds", {})
    if fit_score < thresholds.get("review_needed", 40):
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET submission_status = 'low_fit', notes = 'Fit score below threshold' WHERE id = ?",
                (job_id,),
            )
        result["status"] = "low_fit"
        result["details"] = f"Fit score {fit_score} below threshold"
        return result

    # Stage 5-6: Resume generation
    try:
        resume_paths = generate_resume(job, profile_name, job_id)
        log_run(job_id, "resume_generation", "completed", f"docx={resume_paths.get('docx')}")
    except Exception as e:
        logger.error(f"Resume generation failed: {e}")
        log_error(job_id, "resume_generation", str(e))
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET submission_status = 'blocked', notes = ? WHERE id = ?",
                (f"Resume generation failed: {e}", job_id),
            )
        result["status"] = "blocked"
        result["details"] = f"Resume generation failed: {e}"
        return result

    # Stage 7: Cover letter (only if needed)
    cover_letter_paths = None
    try:
        cover_letter_paths = generate_cover_letter(
            job, Path(resume_paths["folder"]), job_id
        )
        if cover_letter_paths:
            log_run(job_id, "cover_letter", "completed")
    except Exception as e:
        logger.warning(f"Cover letter generation failed (non-blocking): {e}")

    # Stage 8-9: Application routing
    if job.apply_link:
        # Case 1: Form fill
        result["status"] = "form_filling"
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET apply_method = 'form', submission_status = 'form_filling' WHERE id = ?",
                (job_id,),
            )

        try:
            form_result = await fill_and_submit_form(
                job.apply_link, job, resume_paths, cover_letter_paths, job_id
            )
            if form_result.get("submitted"):
                result["status"] = "submitted"
                result["details"] = f"Form submitted at {job.apply_link}"
            elif form_result.get("blocked"):
                result["status"] = "blocked"
                result["details"] = f"Blocked: {form_result.get('block_reason', 'unknown')}"
            else:
                result["status"] = "form_filled"
                result["details"] = f"Form filled ({form_result.get('filled_count', 0)} fields) but not submitted"
        except Exception as e:
            logger.error(f"Form filling failed: {e}")
            log_error(job_id, "form_fill", str(e))
            result["status"] = "blocked"
            result["details"] = f"Form fill error: {e}"

    elif job.apply_email:
        # Case 2: Email application
        result["status"] = "sending_email"
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET apply_method = 'email', submission_status = 'sending_email' WHERE id = ?",
                (job_id,),
            )

        sent = send_application_email(job, resume_paths, cover_letter_paths, job_id)
        if sent:
            result["status"] = "sent"
            result["details"] = f"Email sent to {job.apply_email}"
        else:
            result["status"] = "email_failed"
            result["details"] = f"Failed to send email to {job.apply_email}"

    else:
        # No apply method found
        with get_db() as db:
            db.execute(
                "UPDATE jobs SET submission_status = 'no_apply_method', notes = 'No email or link found' WHERE id = ?",
                (job_id,),
            )
        result["status"] = "no_apply_method"
        result["details"] = "No email or application link found"

    # Mark raw message as processed with full details
    if raw_msg_id:
        with get_db() as db:
            db.execute(
                """UPDATE raw_messages SET
                    processed = 1, processed_at = ?, classification = 'actionable_job_post',
                    is_actionable = 1, processing_result = ?
                WHERE id = ?""",
                (datetime.now().isoformat(), f"status={result['status']}, job_id={job_id}", raw_msg_id),
            )

    logger.info(f"Pipeline complete for job {job_id}: status={result['status']}")
    return result


async def process_messages_batch(messages: list[dict]) -> list[dict]:
    """Process a batch of messages sequentially."""
    results = []
    for msg in messages:
        try:
            result = await process_message(msg)
            results.append(result)
        except Exception as e:
            logger.error(f"Pipeline error for message: {e}")
            results.append({
                "message_id": msg.get("id"),
                "status": "error",
                "details": str(e),
            })
    return results
