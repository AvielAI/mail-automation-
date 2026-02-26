"""Deduplication helpers — record-level dedup within and across runs."""
from __future__ import annotations

import hashlib
from typing import Optional

from app.models.entities import InsuranceRecord


def record_stable_key(record: InsuranceRecord) -> str:
    """Produce a stable key for a record to detect near-duplicates."""
    parts = [
        record.message_id or "",
        record.policy_number or "",
        record.insurance_type or "",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def dedup_records(records: list[InsuranceRecord]) -> list[InsuranceRecord]:
    """Within a list, keep only the highest-confidence record per stable key."""
    seen: dict[str, InsuranceRecord] = {}
    for rec in records:
        key = record_stable_key(rec)
        existing = seen.get(key)
        if existing is None or rec.extraction_confidence > existing.extraction_confidence:
            seen[key] = rec
    return list(seen.values())
