"""SQLite database setup and connection management."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.config import DATABASE_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_hash TEXT UNIQUE NOT NULL,
    whatsapp_group TEXT NOT NULL,
    sender TEXT,
    message_text TEXT NOT NULL,
    normalized_text TEXT,
    whatsapp_timestamp TEXT,
    timestamp TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    captured_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    is_historical INTEGER NOT NULL DEFAULT 0,
    classification TEXT,
    is_actionable INTEGER NOT NULL DEFAULT 0,
    processing_result TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER REFERENCES raw_messages(id),
    capture_date TEXT NOT NULL DEFAULT (datetime('now')),
    whatsapp_group TEXT,
    raw_message TEXT,
    job_title TEXT,
    company TEXT,
    location TEXT,
    role_category TEXT,
    selected_application_profile TEXT,
    fit_score REAL DEFAULT 0,
    apply_method TEXT,
    apply_email TEXT,
    apply_link TEXT,
    apply_phone TEXT,
    requirements TEXT,
    description TEXT,
    job_type TEXT,
    experience_required TEXT,
    detection_confidence REAL DEFAULT 0,
    detection_reason TEXT,
    generated_resume_docx TEXT,
    generated_resume_pdf TEXT,
    generated_cover_letter_docx TEXT,
    generated_cover_letter_pdf TEXT,
    submission_status TEXT NOT NULL DEFAULT 'pending',
    sent_or_not INTEGER NOT NULL DEFAULT 0,
    sent_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS generated_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    file_type TEXT NOT NULL,
    file_format TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS form_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    field_name TEXT NOT NULL,
    field_selector TEXT,
    field_type TEXT,
    filled_value TEXT,
    confidence REAL DEFAULT 0,
    is_risky INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'filled',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    error_message TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    stage TEXT,
    error_type TEXT,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_hash ON raw_messages(message_hash);
CREATE INDEX IF NOT EXISTS idx_raw_messages_group ON raw_messages(whatsapp_group);
CREATE INDEX IF NOT EXISTS idx_raw_messages_processed ON raw_messages(processed);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(submission_status);
CREATE INDEX IF NOT EXISTS idx_jobs_capture_date ON jobs(capture_date);
CREATE INDEX IF NOT EXISTS idx_job_runs_job_id ON job_runs(job_id);
CREATE INDEX IF NOT EXISTS idx_errors_job_id ON errors(job_id);
"""


def get_db_path() -> Path:
    return DATABASE_PATH


def init_db():
    """Initialize the database with schema."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
