"""Simple file-based lock to prevent concurrent sync corruption."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class LockTimeout(Exception):
    pass


@contextmanager
def file_lock(lock_path: Path, timeout: float = 60.0) -> Generator[None, None, None]:
    """Acquire an exclusive lock file; release on context exit."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise LockTimeout(
                    f"Could not acquire lock {lock_path} within {timeout}s"
                )
            # Check if lock is stale (process died)
            try:
                pid = int(lock_path.read_text().strip())
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    lock_path.unlink(missing_ok=True)
                    continue
            except (ValueError, OSError):
                lock_path.unlink(missing_ok=True)
                continue
            time.sleep(0.5)
    try:
        yield
    finally:
        if acquired:
            lock_path.unlink(missing_ok=True)
