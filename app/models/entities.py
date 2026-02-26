"""Domain entities — dataclasses serialisable to/from plain dicts (JSON-friendly)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class InsuranceType(str, Enum):
    CAR = "car"
    HEALTH = "health"
    HOME = "home"
    LIFE = "life"
    TRAVEL = "travel"
    MORTGAGE = "mortgage"
    DISABILITY = "disability"
    OTHER = "other"
    UNKNOWN = "unknown"


class PaymentFrequency(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# OAuth / token state
# ---------------------------------------------------------------------------

@dataclass
class OAuthTokenState:
    token: str = ""
    refresh_token: str = ""
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str = ""
    client_secret: str = ""
    scopes: list[str] = field(default_factory=list)
    expiry: Optional[str] = None  # ISO datetime string

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OAuthTokenState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Gmail message metadata
# ---------------------------------------------------------------------------

@dataclass
class GmailMessageMeta:
    message_id: str = ""
    thread_id: str = ""
    subject: str = ""
    sender: str = ""
    date: str = ""  # ISO datetime string
    snippet: str = ""
    has_attachments: bool = False
    label_ids: list[str] = field(default_factory=list)
    processed_at: Optional[str] = None
    processing_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GmailMessageMeta":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Attachment metadata
# ---------------------------------------------------------------------------

@dataclass
class AttachmentMeta:
    attachment_id: str = ""          # stable record id
    message_id: str = ""
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    sha256: str = ""                  # for dedup
    local_path: Optional[str] = None  # optional cached path
    processed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AttachmentMeta":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Extracted document
# ---------------------------------------------------------------------------

@dataclass
class ExtractedDoc:
    doc_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str = ""
    attachment_id: str = ""          # empty if from body
    source: str = "body"             # body | pdf | ocr
    raw_text: str = ""
    page_count: int = 0
    extraction_warnings: list[str] = field(default_factory=list)
    extracted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractedDoc":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Core insurance record
# ---------------------------------------------------------------------------

@dataclass
class InsuranceRecord:
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str = ""
    attachment_id: str = ""

    # Classification
    insurance_type: str = InsuranceType.UNKNOWN.value
    classification_confidence: float = 0.0
    needs_review: bool = True

    # Core fields
    insurer_company: str = ""
    policy_number: str = ""
    insured_name: str = ""
    id_number_masked: str = ""       # last 4 only

    # Dates
    start_date: str = ""
    end_date: str = ""
    renewal_date: str = ""

    # Financial
    premium_monthly: Optional[float] = None
    premium_yearly: Optional[float] = None
    premium_monthly_derived: bool = False   # True if computed from annual
    premium_yearly_derived: bool = False    # True if computed from monthly
    payment_frequency: str = PaymentFrequency.UNKNOWN.value
    currency: str = ""
    amount_due: Optional[float] = None
    payment_status: str = ""

    # Type-specific
    vehicle_number: str = ""
    property_address: str = ""

    # Agent
    agent_name: str = ""
    agency_name: str = ""

    # Source provenance
    source_email_subject: str = ""
    source_email_date: str = ""
    source_email_sender: str = ""
    source_attachment_filename: str = ""

    # Meta
    extraction_confidence: float = 0.0
    extraction_notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InsuranceRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Sync run summary
# ---------------------------------------------------------------------------

@dataclass
class SyncRunSummary:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None
    messages_found: int = 0
    messages_new: int = 0
    messages_skipped: int = 0
    attachments_processed: int = 0
    records_created: int = 0
    records_needs_review: int = 0
    errors: int = 0
    status: str = "running"          # running | completed | failed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SyncRunSummary":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Processing error
# ---------------------------------------------------------------------------

@dataclass
class ProcessingError:
    error_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str = ""
    attachment_id: str = ""
    stage: str = ""                  # fetch | extract | classify | export
    error_type: str = ""
    error_msg: str = ""
    occurred_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProcessingError":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
