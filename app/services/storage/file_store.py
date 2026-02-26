"""Low-level file-based key/value store operations."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_json, read_json, append_jsonl


class FileStore:
    """Provides typed read/write helpers over a DATA_DIR layout."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.state_dir = data_dir / "state"
        self.attachments_dir = data_dir / "attachments"
        self.extracted_dir = data_dir / "extracted_text"
        self.exports_dir = data_dir / "exports"
        self.lock_path = data_dir / "sync.lock"
        self._ensure_dirs()

    # ------------------------------------------------------------------
    def _ensure_dirs(self) -> None:
        for d in [
            self.state_dir,
            self.attachments_dir,
            self.extracted_dir,
            self.exports_dir,
        ]:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------ oauth
    @property
    def oauth_token_path(self) -> Path:
        return self.state_dir / "oauth_tokens.json"

    def load_oauth_token(self) -> dict | None:
        return read_json(self.oauth_token_path)

    def save_oauth_token(self, data: dict) -> None:
        atomic_write_json(self.oauth_token_path, data)

    def delete_oauth_token(self) -> None:
        self.oauth_token_path.unlink(missing_ok=True)

    # ----------------------------------------------- processed messages index
    @property
    def processed_messages_path(self) -> Path:
        return self.state_dir / "processed_messages.json"

    def load_processed_messages(self) -> dict[str, str]:
        """Returns {message_id: processed_at_iso}."""
        return read_json(self.processed_messages_path, default={})

    def save_processed_messages(self, data: dict[str, str]) -> None:
        atomic_write_json(self.processed_messages_path, data)

    # -------------------------------------------- processed attachments index
    @property
    def processed_attachments_path(self) -> Path:
        return self.state_dir / "processed_attachments.json"

    def load_processed_attachments(self) -> dict[str, str]:
        """Returns {sha256: processed_at_iso}."""
        return read_json(self.processed_attachments_path, default={})

    def save_processed_attachments(self, data: dict[str, str]) -> None:
        atomic_write_json(self.processed_attachments_path, data)

    # ------------------------------------------------------- insurance records
    @property
    def records_path(self) -> Path:
        return self.state_dir / "insurance_records.json"

    def load_records(self) -> list[dict]:
        return read_json(self.records_path, default=[])

    def save_records(self, records: list[dict]) -> None:
        atomic_write_json(self.records_path, records)

    # -------------------------------------------------------------------- log
    @property
    def run_log_path(self) -> Path:
        return self.state_dir / "run_log.jsonl"

    def append_log(self, entry: dict) -> None:
        append_jsonl(self.run_log_path, entry)

    def load_log_lines(self, tail: int = 200) -> list[dict]:
        import json
        try:
            lines = self.run_log_path.read_text(encoding="utf-8").splitlines()
            result = []
            for ln in lines[-tail:]:
                try:
                    result.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
            return result
        except FileNotFoundError:
            return []

    # -------------------------------------------------- extracted text cache
    def extracted_text_path(self, doc_id: str) -> Path:
        return self.extracted_dir / f"{doc_id}.txt"

    def save_extracted_text(self, doc_id: str, text: str) -> None:
        from .atomic_io import atomic_write_text
        atomic_write_text(self.extracted_text_path(doc_id), text)

    # -------------------------------------------------- attachment cache
    def attachment_path(self, sha256: str, filename: str) -> Path:
        ext = Path(filename).suffix or ".bin"
        return self.attachments_dir / f"{sha256}{ext}"

    # -------------------------------------------------- exports
    @property
    def excel_export_path(self) -> Path:
        return self.exports_dir / "insurance_tracker.xlsx"
