"""Insurance type classification + field extraction pipeline."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from app.models.entities import (
    ExtractedDoc,
    GmailMessageMeta,
    InsuranceRecord,
    InsuranceType,
)
from app.services.extraction.parsers import extract_fields

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword banks for classification
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS: dict[str, dict[str, list[str]]] = {
    InsuranceType.CAR.value: {
        "he": ["רכב", "מכונית", "אוטו", "לוחית", "קולט", "טסט", "רכב פרטי", "ביטוח רכב", "חובה"],
        "en": ["car", "vehicle", "auto", "motor", "compulsory", "third party", "collision", "comprehensive vehicle"],
    },
    InsuranceType.HEALTH.value: {
        "he": ["בריאות", "רפואה", "אשפוז", "תרופות", "ניתוח", "ביטוח בריאות", "מחלה", "סיעוד", "ביטוח רפואי"],
        "en": ["health", "medical", "hospitalization", "surgery", "nursing", "illness", "sick"],
    },
    InsuranceType.HOME.value: {
        "he": ["דירה", "בית", "מבנה", "תכולה", "שכירות", "ביטוח דירה", "ביטוח בית", "נכס"],
        "en": ["home", "house", "property", "building", "contents", "dwelling", "apartment", "renters"],
    },
    InsuranceType.LIFE.value: {
        "he": ["חיים", "ביטוח חיים", "מות", "פטירה", "שארים", "ריסק"],
        "en": ["life", "death", "mortality", "term life", "whole life"],
    },
    InsuranceType.TRAVEL.value: {
        "he": ["נסיעות", "טיול", "טיסה", "ביטוח נסיעות", "חו\"ל"],
        "en": ["travel", "trip", "flight", "journey", "abroad", "overseas"],
    },
    InsuranceType.MORTGAGE.value: {
        "he": ["משכנתא", "הלוואה", "בנק", "ריבית", "מחזיק", "ביטוח משכנתא"],
        "en": ["mortgage", "loan", "lender", "bank guarantee"],
    },
    InsuranceType.DISABILITY.value: {
        "he": ["אובדן כושר", "נכות", "שיקום", "תאונה", "ביטוח אובדן"],
        "en": ["disability", "incapacity", "accident", "loss of capacity", "work accident"],
    },
}

_CONFIDENCE_THRESHOLD_REVIEW = 0.45  # below this → needs_review = True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_and_extract(
    meta: GmailMessageMeta,
    docs: list[ExtractedDoc],
) -> list[InsuranceRecord]:
    """Classify insurance type and extract fields from all docs for a message."""
    combined_text = _combine_text(meta, docs)
    ins_type, class_confidence = _classify(combined_text)

    # Extract fields from combined text
    fields = extract_fields(combined_text)

    # Build confidence score
    filled = sum(1 for v in fields.values() if v)
    total = len(fields)
    field_confidence = filled / total if total else 0.0
    overall_confidence = (class_confidence * 0.5 + field_confidence * 0.5)

    notes_parts = []
    if class_confidence < _CONFIDENCE_THRESHOLD_REVIEW:
        notes_parts.append(f"Low classification confidence ({class_confidence:.2f})")
    for doc in docs:
        notes_parts.extend(doc.extraction_warnings)

    record = InsuranceRecord(
        message_id=meta.message_id,
        attachment_id=docs[0].attachment_id if docs else "",
        insurance_type=ins_type,
        classification_confidence=round(class_confidence, 3),
        needs_review=overall_confidence < _CONFIDENCE_THRESHOLD_REVIEW,
        insurer_company=fields.get("insurer_company", ""),
        policy_number=fields.get("policy_number", ""),
        insured_name=fields.get("insured_name", ""),
        id_number_masked=fields.get("id_number_masked", ""),
        start_date=fields.get("start_date", ""),
        end_date=fields.get("end_date", ""),
        renewal_date=fields.get("renewal_date", ""),
        premium_monthly=fields.get("premium_monthly"),
        premium_yearly=fields.get("premium_yearly"),
        premium_monthly_derived=fields.get("premium_monthly_derived", False),
        premium_yearly_derived=fields.get("premium_yearly_derived", False),
        payment_frequency="monthly" if fields.get("premium_monthly") else "annual",
        currency=fields.get("currency", "ILS"),
        amount_due=fields.get("amount_due"),
        vehicle_number=fields.get("vehicle_number", ""),
        property_address=fields.get("property_address", ""),
        agent_name=fields.get("agent_name", ""),
        agency_name=fields.get("agency_name", ""),
        source_email_subject=meta.subject,
        source_email_date=meta.date,
        source_email_sender=meta.sender,
        source_attachment_filename=_first_attachment_filename(docs),
        extraction_confidence=round(overall_confidence, 3),
        extraction_notes="; ".join(notes_parts)[:500],
    )

    return [record]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(text: str) -> tuple[str, float]:
    """Return (insurance_type, confidence 0-1)."""
    text_lower = text.lower()
    scores: dict[str, float] = {}

    for ins_type, kw_sets in _TYPE_KEYWORDS.items():
        score = 0.0
        for lang, keywords in kw_sets.items():
            for kw in keywords:
                if kw in text_lower:
                    score += 1.0
        scores[ins_type] = score

    if not any(scores.values()):
        return InsuranceType.UNKNOWN.value, 0.0

    best_type = max(scores, key=lambda t: scores[t])
    best_score = scores[best_type]
    total_score = sum(scores.values())
    confidence = best_score / total_score if total_score else 0.0

    # Normalise to 0-1 (cap at reasonable value)
    confidence = min(confidence * 2.0, 1.0)  # boost since multiple keywords hit
    return best_type, round(confidence, 3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _combine_text(meta: GmailMessageMeta, docs: list[ExtractedDoc]) -> str:
    parts = [meta.subject, meta.snippet]
    for doc in docs:
        parts.append(doc.raw_text)
    return "\n".join(p for p in parts if p)


def _first_attachment_filename(docs: list[ExtractedDoc]) -> str:
    for doc in docs:
        if doc.source in ("pdf", "ocr") and doc.attachment_id:
            # attachment_id is "message_id_att_id" — we don't store filename here
            # so return empty; caller can cross-ref AttachmentMeta if needed
            return ""
    return ""
