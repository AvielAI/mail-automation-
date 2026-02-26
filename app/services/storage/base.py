"""Storage abstraction base — thin wrapper that initialises all repositories."""
from __future__ import annotations

from pathlib import Path

from .file_store import FileStore
from .repositories import RecordRepository, ErrorRepository, SyncLogRepository


class Storage:
    """Facade that owns all repositories; pass this around the app."""

    def __init__(self, data_dir: Path) -> None:
        self.store = FileStore(data_dir)
        self.records = RecordRepository(self.store)
        self.errors = ErrorRepository(self.store)
        self.sync_log = SyncLogRepository(self.store)

    # ---------------------------------------------------------------- helpers
    def is_message_processed(self, message_id: str) -> bool:
        processed = self.store.load_processed_messages()
        return message_id in processed

    def mark_message_processed(self, message_id: str, processed_at: str) -> None:
        processed = self.store.load_processed_messages()
        processed[message_id] = processed_at
        self.store.save_processed_messages(processed)

    def is_attachment_processed(self, sha256: str) -> bool:
        processed = self.store.load_processed_attachments()
        return sha256 in processed

    def mark_attachment_processed(self, sha256: str, processed_at: str) -> None:
        processed = self.store.load_processed_attachments()
        processed[sha256] = processed_at
        self.store.save_processed_attachments(processed)
