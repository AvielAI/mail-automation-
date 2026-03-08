"""Job data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DetectionResult:
    is_job_post: bool = False
    is_actionable: bool = False
    confidence: float = 0.0
    reason: str = ""
    detected_signals: list[str] = field(default_factory=list)


@dataclass
class ExtractedJob:
    job_title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    requirements: str = ""
    job_type: str = ""
    experience_required: str = ""
    apply_email: str = ""
    apply_link: str = ""
    apply_phone: str = ""
    role_category: str = ""
    raw_message: str = ""
    whatsapp_group: str = ""
    detection_confidence: float = 0.0
    detection_reason: str = ""


@dataclass
class JobRecord:
    id: Optional[int] = None
    raw_message_id: Optional[int] = None
    capture_date: str = ""
    whatsapp_group: str = ""
    raw_message: str = ""
    job_title: str = ""
    company: str = ""
    location: str = ""
    role_category: str = ""
    selected_application_profile: str = ""
    fit_score: float = 0.0
    apply_method: str = ""
    apply_email: str = ""
    apply_link: str = ""
    apply_phone: str = ""
    requirements: str = ""
    description: str = ""
    job_type: str = ""
    experience_required: str = ""
    detection_confidence: float = 0.0
    detection_reason: str = ""
    generated_resume_docx: str = ""
    generated_resume_pdf: str = ""
    generated_cover_letter_docx: str = ""
    generated_cover_letter_pdf: str = ""
    submission_status: str = "pending"
    sent_or_not: bool = False
    sent_date: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "JobRecord":
        return cls(**{k: row[k] for k in row.keys() if k in cls.__dataclass_fields__})
