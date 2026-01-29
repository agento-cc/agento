from __future__ import annotations

import shutil
import time
from pathlib import Path


class LockHeld(Exception):
    pass


class FileLock:
    """mkdir-based lock with stale detection."""

    def __init__(self, lock_dir: str = "/tmp/sync-jira-cron.lock", stale_seconds: int = 300):
        self.lock_dir = Path(lock_dir)
        self.stale_seconds = stale_seconds

    def __enter__(self) -> FileLock:
        try:
            self.lock_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            age = time.time() - self.lock_dir.stat().st_mtime
            if age > self.stale_seconds:
                shutil.rmtree(self.lock_dir)
                self.lock_dir.mkdir(parents=True, exist_ok=False)
            else:
                raise LockHeld(f"Lock held (age: {age:.0f}s)") from None
        return self

    def __exit__(self, *exc: object) -> None:
        shutil.rmtree(self.lock_dir, ignore_errors=True)
