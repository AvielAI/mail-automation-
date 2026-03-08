"""Email sender service for sending application emails."""

import logging
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.core.config import Config
from app.core.database import get_db
from app.models.job import ExtractedJob

logger = logging.getLogger(__name__)


def build_subject(job: ExtractedJob) -> str:
    """Build email subject line."""
    candidate = Config.get().candidate
    name = candidate.get("full_name", "Applicant")
    if job.job_title:
        return f"Application for {job.job_title} – {name}"
    return f"Job Application – {name}"


def build_body(job: ExtractedJob) -> str:
    """Build email body - short, professional, neutral."""
    candidate = Config.get().candidate
    title = job.job_title or "the open position"

    return (
        f"Hello,\n\n"
        f"I would like to apply for the {title} position.\n"
        f"Please find my tailored resume attached for your review.\n\n"
        f"Thank you for your time and consideration.\n\n"
        f"Best regards,\n"
        f"{candidate.get('full_name', '')}\n"
        f"{candidate.get('phone', '')}\n"
        f"{candidate.get('email', '')}"
    )


def send_application_email(
    job: ExtractedJob,
    resume_paths: dict,
    cover_letter_paths: dict | None = None,
    job_id: int | None = None,
) -> bool:
    """Send application email with resume attached.

    Prefers PDF, falls back to DOCX.
    Returns True if sent successfully.
    """
    config = Config.get()
    email_settings = config.email_settings

    if not email_settings.get("sender_email") or not email_settings.get("sender_password"):
        logger.error("Email credentials not configured. Set SENDER_EMAIL and SENDER_EMAIL_PASSWORD env vars.")
        _log_error(job_id, "Email credentials not configured")
        return False

    if not job.apply_email:
        logger.error("No recipient email address for this job")
        _log_error(job_id, "No recipient email")
        return False

    # Build message
    msg = MIMEMultipart()
    msg["From"] = email_settings["sender_email"]
    msg["To"] = job.apply_email
    msg["Subject"] = build_subject(job)
    msg.attach(MIMEText(build_body(job), "plain", "utf-8"))

    # Attach resume (PDF preferred)
    resume_attached = False
    for fmt in ["pdf", "docx"]:
        path = resume_paths.get(fmt)
        if path and Path(path).exists():
            _attach_file(msg, Path(path))
            resume_attached = True
            break

    if not resume_attached:
        logger.error("No resume file available to attach")
        _log_error(job_id, "No resume file to attach")
        return False

    # Attach cover letter if available
    if cover_letter_paths:
        for fmt in ["pdf", "docx"]:
            path = cover_letter_paths.get(fmt)
            if path and Path(path).exists():
                _attach_file(msg, Path(path))
                break

    # Send
    try:
        with smtplib.SMTP(email_settings["smtp_server"], email_settings["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_settings["sender_email"], email_settings["sender_password"])
            server.send_message(msg)

        logger.info(f"Application email sent to {job.apply_email}")

        if job_id:
            with get_db() as db:
                db.execute(
                    """UPDATE jobs SET
                        submission_status = 'sent',
                        sent_or_not = 1,
                        sent_date = ?,
                        apply_method = 'email',
                        notes = COALESCE(notes, '') || ' | Email sent to ' || ?
                    WHERE id = ?""",
                    (datetime.now().isoformat(), job.apply_email, job_id),
                )
                db.execute(
                    "INSERT INTO job_runs (job_id, stage, status, finished_at, details) VALUES (?, ?, ?, ?, ?)",
                    (job_id, "email_send", "completed", datetime.now().isoformat(), f"Sent to {job.apply_email}"),
                )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed. Check email credentials.")
        _log_error(job_id, "SMTP authentication failed")
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        _log_error(job_id, f"SMTP error: {e}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        _log_error(job_id, f"Email send failed: {e}")

    return False


def _attach_file(msg: MIMEMultipart, file_path: Path):
    """Attach a file to the email message."""
    with open(file_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=file_path.name)
    part["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
    msg.attach(part)


def _log_error(job_id: int | None, message: str):
    """Log error to database."""
    if job_id:
        with get_db() as db:
            db.execute(
                "INSERT INTO errors (job_id, stage, error_type, error_message) VALUES (?, ?, ?, ?)",
                (job_id, "email_send", "email_error", message),
            )
            db.execute(
                "UPDATE jobs SET submission_status = 'email_failed', notes = COALESCE(notes, '') || ? WHERE id = ?",
                (f" | Error: {message}", job_id),
            )
