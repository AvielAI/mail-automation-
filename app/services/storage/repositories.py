"""High-level repository layer — domain model ↔ file store."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.models.entities import InsuranceRecord, ProcessingError, SyncRunSummary
from .file_store import FileStore


class RecordRepository:
    def __init__(self, store: FileStore) -> None:
        self._store = store

    def all(self) -> list[InsuranceRecord]:
        return [InsuranceRecord.from_dict(d) for d in self._store.load_records()]

    def save_all(self, records: list[InsuranceRecord]) -> None:
        self._store.save_records([r.to_dict() for r in records])

    def upsert(self, record: InsuranceRecord) -> None:
        """Insert or replace by record_id."""
        records = self.all()
        idx = next((i for i, r in enumerate(records) if r.record_id == record.record_id), None)
        if idx is not None:
            records[idx] = record
        else:
            records.append(record)
        self.save_all(records)

    def upsert_many(self, new_records: list[InsuranceRecord]) -> None:
        existing = {r.record_id: r for r in self.all()}
        for r in new_records:
            existing[r.record_id] = r
        self.save_all(list(existing.values()))

    def needs_review(self) -> list[InsuranceRecord]:
        return [r for r in self.all() if r.needs_review]

    def by_type(self, insurance_type: str) -> list[InsuranceRecord]:
        return [r for r in self.all() if r.insurance_type == insurance_type]

    def count(self) -> int:
        return len(self._store.load_records())


class ErrorRepository:
    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._path = store.state_dir / "processing_errors.json"

    def _load(self) -> list[dict]:
        from app.services.storage.atomic_io import read_json
        return read_json(self._path, default=[])

    def _save(self, errors: list[dict]) -> None:
        from app.services.storage.atomic_io import atomic_write_json
        atomic_write_json(self._path, errors)

    def all(self) -> list[ProcessingError]:
        return [ProcessingError.from_dict(d) for d in self._load()]

    def append(self, error: ProcessingError) -> None:
        errors = self._load()
        errors.append(error.to_dict())
        self._save(errors)

    def clear(self) -> None:
        self._save([])

    def recent(self, n: int = 50) -> list[ProcessingError]:
        return self.all()[-n:]


class SyncLogRepository:
    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._path = store.state_dir / "sync_runs.json"

    def _load(self) -> list[dict]:
        from app.services.storage.atomic_io import read_json
        return read_json(self._path, default=[])

    def _save(self, runs: list[dict]) -> None:
        from app.services.storage.atomic_io import atomic_write_json
        atomic_write_json(self._path, runs)

    def append(self, summary: SyncRunSummary) -> None:
        runs = self._load()
        runs.append(summary.to_dict())
        # Keep last 100 runs
        if len(runs) > 100:
            runs = runs[-100:]
        self._save(runs)

    def update(self, summary: SyncRunSummary) -> None:
        runs = self._load()
        for i, r in enumerate(runs):
            if r.get("run_id") == summary.run_id:
                runs[i] = summary.to_dict()
                break
        else:
            runs.append(summary.to_dict())
        self._save(runs)

    def last(self) -> Optional[SyncRunSummary]:
        runs = self._load()
        if not runs:
            return None
        return SyncRunSummary.from_dict(runs[-1])

    def all(self) -> list[SyncRunSummary]:
        return [SyncRunSummary.from_dict(d) for d in self._load()]
