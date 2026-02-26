"""Tests for storage layer."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from app.services.storage.atomic_io import atomic_write_json, read_json, append_jsonl
from app.services.storage.file_store import FileStore
from app.services.storage.base import Storage
from app.models.entities import InsuranceRecord, SyncRunSummary, ProcessingError


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def store(tmp_data_dir):
    return FileStore(tmp_data_dir)


@pytest.fixture
def storage(tmp_data_dir):
    return Storage(tmp_data_dir)


# ---------------------------------------------------------------------------
# atomic_io
# ---------------------------------------------------------------------------

def test_atomic_write_and_read_json(tmp_path):
    path = tmp_path / "test.json"
    data = {"key": "value", "num": 42}
    atomic_write_json(path, data)
    assert path.exists()
    result = read_json(path)
    assert result == data


def test_read_json_missing_file(tmp_path):
    path = tmp_path / "missing.json"
    result = read_json(path, default={"default": True})
    assert result == {"default": True}


def test_read_json_corrupt_file(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("not json!", encoding="utf-8")
    result = read_json(path, default=[])
    assert result == []


def test_append_jsonl(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"event": "test", "val": 1})
    append_jsonl(path, {"event": "test2", "val": 2})
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["val"] == 1
    assert json.loads(lines[1])["val"] == 2


# ---------------------------------------------------------------------------
# FileStore
# ---------------------------------------------------------------------------

def test_oauth_token_roundtrip(store):
    data = {"token": "abc", "refresh_token": "xyz"}
    store.save_oauth_token(data)
    assert store.load_oauth_token() == data


def test_delete_oauth_token(store):
    store.save_oauth_token({"token": "abc"})
    store.delete_oauth_token()
    assert store.load_oauth_token() is None


def test_processed_messages_roundtrip(store):
    store.save_processed_messages({"msg1": "2024-01-01"})
    result = store.load_processed_messages()
    assert result["msg1"] == "2024-01-01"


def test_processed_messages_default_empty(store):
    result = store.load_processed_messages()
    assert result == {}


def test_records_roundtrip(store):
    r = InsuranceRecord(policy_number="12345", insurer_company="TestCo")
    store.save_records([r.to_dict()])
    loaded = store.load_records()
    assert len(loaded) == 1
    assert loaded[0]["policy_number"] == "12345"


def test_log_append_and_load(store):
    store.append_log({"event": "test", "ts": "2024-01-01T00:00:00"})
    lines = store.load_log_lines()
    assert len(lines) == 1
    assert lines[0]["event"] == "test"


# ---------------------------------------------------------------------------
# Storage (facade)
# ---------------------------------------------------------------------------

def test_mark_message_processed(storage):
    assert not storage.is_message_processed("msg1")
    storage.mark_message_processed("msg1", "2024-01-01")
    assert storage.is_message_processed("msg1")


def test_mark_attachment_processed(storage):
    sha = "abc123"
    assert not storage.is_attachment_processed(sha)
    storage.mark_attachment_processed(sha, "2024-01-01")
    assert storage.is_attachment_processed(sha)


def test_record_upsert(storage):
    r1 = InsuranceRecord(policy_number="P001")
    r2 = InsuranceRecord(record_id=r1.record_id, policy_number="P001-updated")
    storage.records.upsert(r1)
    storage.records.upsert(r2)
    all_rec = storage.records.all()
    assert len(all_rec) == 1
    assert all_rec[0].policy_number == "P001-updated"


def test_record_needs_review(storage):
    r1 = InsuranceRecord(needs_review=True)
    r2 = InsuranceRecord(needs_review=False)
    storage.records.upsert(r1)
    storage.records.upsert(r2)
    review = storage.records.needs_review()
    assert len(review) == 1
    assert review[0].needs_review


def test_error_repository(storage):
    err = ProcessingError(stage="fetch", error_type="ValueError", error_msg="test error")
    storage.errors.append(err)
    all_errors = storage.errors.all()
    assert len(all_errors) == 1
    assert all_errors[0].error_msg == "test error"


def test_sync_log_append_and_last(storage):
    run = SyncRunSummary(status="completed", messages_found=10)
    storage.sync_log.append(run)
    last = storage.sync_log.last()
    assert last is not None
    assert last.messages_found == 10
    assert last.status == "completed"


def test_sync_log_update(storage):
    run = SyncRunSummary(status="running")
    storage.sync_log.append(run)
    run.status = "completed"
    run.records_created = 5
    storage.sync_log.update(run)
    last = storage.sync_log.last()
    assert last.status == "completed"
    assert last.records_created == 5
