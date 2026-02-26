"""Gmail API service — search, fetch messages and attachments."""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from email import message_from_bytes
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Config
from app.models.entities import (
    AttachmentMeta,
    ExtractedDoc,
    GmailMessageMeta,
    InsuranceRecord,
    ProcessingError,
    SyncRunSummary,
)
from app.services.storage.base import Storage
from app.services.storage.locks import file_lock, LockTimeout
from app.utils.helpers import sha256_bytes, now_iso

logger = logging.getLogger(__name__)

SUPPORTED_ATTACHMENT_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/tiff",
    "image/gif",
    "image/bmp",
    "image/webp",
}


class GmailSyncService:
    def __init__(
        self,
        storage: Storage,
        credentials: Credentials,
        custom_query: Optional[str] = None,
    ) -> None:
        self._storage = storage
        self._credentials = credentials
        self._query = custom_query or Config.GMAIL_SEARCH_QUERY
        self._service = build("gmail", "v1", credentials=credentials)

    # ----------------------------------------------------------------- public

    def run(self) -> SyncRunSummary:
        summary = SyncRunSummary()
        self._storage.sync_log.append(summary)
        self._storage.store.append_log(
            {"event": "sync_start", "run_id": summary.run_id, "ts": now_iso()}
        )

        try:
            lock_path = self._storage.store.lock_path
            with file_lock(lock_path, timeout=10.0):
                self._execute(summary)
        except LockTimeout:
            summary.status = "failed"
            summary.errors += 1
            self._log_error(ProcessingError(
                stage="fetch",
                error_type="LockTimeout",
                error_msg="Another sync is already running",
            ))
        except Exception as exc:
            logger.exception("Sync failed: %s", exc)
            summary.status = "failed"
            summary.errors += 1
        finally:
            summary.finished_at = now_iso()
            if summary.status == "running":
                summary.status = "completed"
            self._storage.sync_log.update(summary)
            self._storage.store.append_log(
                {"event": "sync_end", "run_id": summary.run_id,
                 "status": summary.status, "ts": now_iso()}
            )

        return summary

    # --------------------------------------------------------------- internals

    def _execute(self, summary: SyncRunSummary) -> None:
        message_ids = self._list_messages()
        summary.messages_found = len(message_ids)
        logger.info("Found %d messages matching query", len(message_ids))

        new_records: list[InsuranceRecord] = []

        for msg_id in message_ids:
            if self._storage.is_message_processed(msg_id):
                summary.messages_skipped += 1
                continue

            summary.messages_new += 1
            try:
                records = self._process_message(msg_id, summary)
                new_records.extend(records)
            except Exception as exc:
                logger.error("Error processing message %s: %s", msg_id, exc)
                summary.errors += 1
                self._log_error(ProcessingError(
                    message_id=msg_id,
                    stage="fetch",
                    error_type=type(exc).__name__,
                    error_msg=str(exc)[:500],
                ))

        # Persist all new records in one write
        if new_records:
            self._storage.records.upsert_many(new_records)
        summary.records_created = len(new_records)
        summary.records_needs_review = sum(1 for r in new_records if r.needs_review)

    def _list_messages(self) -> list[str]:
        """Return list of message IDs matching the search query."""
        ids: list[str] = []
        page_token = None
        max_results = Config.GMAIL_MAX_RESULTS

        while True:
            params: dict = {
                "userId": "me",
                "q": self._query,
                "maxResults": min(500, max_results - len(ids)),
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                resp = self._service.users().messages().list(**params).execute()
            except HttpError as exc:
                logger.error("Gmail list error: %s", exc)
                break

            messages = resp.get("messages", [])
            ids.extend(m["id"] for m in messages)
            page_token = resp.get("nextPageToken")
            if not page_token or len(ids) >= max_results:
                break

        return ids

    def _process_message(
        self, message_id: str, summary: SyncRunSummary
    ) -> list[InsuranceRecord]:
        """Fetch message, extract text, classify, return InsuranceRecords."""
        msg = self._service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        meta = self._parse_message_meta(message_id, msg)
        all_texts: list[ExtractedDoc] = []

        # --- body
        body_text = self._extract_body(msg)
        if body_text:
            all_texts.append(ExtractedDoc(
                message_id=message_id,
                source="body",
                raw_text=body_text,
            ))

        # --- attachments
        parts = self._collect_parts(msg.get("payload", {}))
        for part in parts:
            mime = part.get("mimeType", "")
            fname = part.get("filename", "")
            att_id = (part.get("body") or {}).get("attachmentId")
            if not att_id or mime not in SUPPORTED_ATTACHMENT_MIME:
                continue

            try:
                att_doc = self._process_attachment(
                    message_id, att_id, fname, mime, summary
                )
                if att_doc:
                    all_texts.append(att_doc)
            except Exception as exc:
                logger.error("Attachment error %s/%s: %s", message_id, fname, exc)
                summary.errors += 1
                self._log_error(ProcessingError(
                    message_id=message_id,
                    stage="extract",
                    error_type=type(exc).__name__,
                    error_msg=str(exc)[:500],
                ))

        # --- classify + extract
        from app.services.classification_service import classify_and_extract
        records = classify_and_extract(meta, all_texts)

        # Mark message processed
        self._storage.mark_message_processed(message_id, now_iso())
        return records

    def _process_attachment(
        self,
        message_id: str,
        att_id: str,
        filename: str,
        mime: str,
        summary: SyncRunSummary,
    ) -> Optional[ExtractedDoc]:
        # Download raw bytes
        att_resp = (
            self._service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=att_id)
            .execute()
        )
        data_b64 = att_resp.get("data", "")
        raw_bytes = base64.urlsafe_b64decode(data_b64 + "==")
        sha = sha256_bytes(raw_bytes)

        att_meta = AttachmentMeta(
            attachment_id=f"{message_id}_{att_id}",
            message_id=message_id,
            filename=filename,
            mime_type=mime,
            size_bytes=len(raw_bytes),
            sha256=sha,
        )

        if self._storage.is_attachment_processed(sha):
            logger.debug("Skipping duplicate attachment sha=%s", sha[:8])
            return None

        # Cache to disk (best-effort)
        cache_path = self._storage.store.attachment_path(sha, filename)
        try:
            from app.services.storage.atomic_io import atomic_write_bytes
            atomic_write_bytes(cache_path, raw_bytes)
            att_meta.local_path = str(cache_path)
        except OSError:
            pass

        # Extract text
        from app.services.extraction.pdf_extractor import extract_from_bytes
        doc = extract_from_bytes(
            raw_bytes,
            mime_type=mime,
            filename=filename,
            message_id=message_id,
            attachment_id=att_meta.attachment_id,
        )

        # Cache extracted text (best-effort)
        if doc.raw_text:
            try:
                self._storage.store.save_extracted_text(doc.doc_id, doc.raw_text)
            except OSError:
                pass

        self._storage.mark_attachment_processed(sha, now_iso())
        summary.attachments_processed += 1
        return doc

    # ----------------------------------------------------------------- helpers

    def _parse_message_meta(self, message_id: str, msg: dict) -> GmailMessageMeta:
        headers = {
            h["name"].lower(): h["value"]
            for h in (msg.get("payload") or {}).get("headers", [])
        }
        date_str = headers.get("date", "")
        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        has_att = bool(self._collect_parts(msg.get("payload", {})))
        return GmailMessageMeta(
            message_id=message_id,
            thread_id=msg.get("threadId", ""),
            subject=subject,
            sender=sender,
            date=date_str,
            snippet=msg.get("snippet", "")[:200],
            has_attachments=has_att,
            label_ids=msg.get("labelIds", []),
        )

    def _extract_body(self, msg: dict) -> str:
        """Decode email body — prefer text/plain, fall back to text/html stripped."""
        payload = msg.get("payload", {})
        text = self._find_body_part(payload, "text/plain")
        if not text:
            html = self._find_body_part(payload, "text/html")
            if html:
                text = re.sub(r"<[^>]+>", " ", html)
        return (text or "").strip()

    def _find_body_part(self, payload: dict, mime: str) -> str:
        """Recursively search MIME parts for desired content type."""
        if payload.get("mimeType") == mime:
            data = (payload.get("body") or {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            result = self._find_body_part(part, mime)
            if result:
                return result
        return ""

    @staticmethod
    def _collect_parts(payload: dict) -> list[dict]:
        """Collect all leaf MIME parts (for attachment detection)."""
        parts = []
        if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
            parts.append(payload)
        for part in payload.get("parts", []):
            parts.extend(GmailSyncService._collect_parts(part))
        return parts

    def _log_error(self, error: ProcessingError) -> None:
        self._storage.errors.append(error)
        self._storage.store.append_log({
            "event": "error",
            "stage": error.stage,
            "type": error.error_type,
            "msg": error.error_msg[:200],
            "ts": error.occurred_at,
        })
