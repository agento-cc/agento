from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ConsumerConfig:
    """Framework-level consumer tuning config."""

    # Per-run isolation (Phase 9.5) eliminates shared .claude.json corruption.
    # Safe to increase max_workers now — each job gets its own run directory.
    max_workers: int = 1
    poll_interval: float = 5.0
    job_timeout_seconds: int = 1200  # 20 minutes
    disable_llm: bool = False

    @property
    def concurrency(self) -> int:
        """Backward-compatible alias for max_workers."""
        return self.max_workers

    @classmethod
    def from_env(cls) -> ConsumerConfig:
        """Build from env vars only."""
        max_workers = int(
            os.environ.get("CONSUMER_MAX_WORKERS")
        )
        return cls(
            max_workers=max_workers,
            poll_interval=float(os.environ.get("CONSUMER_POLL_INTERVAL", "5.0")),
            job_timeout_seconds=int(os.environ.get("JOB_TIMEOUT_SECONDS", "1200")),
            disable_llm=os.environ.get("DISABLE_LLM", "0").lower() in ("1", "true", "yes"),
        )

    @classmethod
    def from_env_and_json(cls, data: dict | None = None) -> ConsumerConfig:
        """Deprecated: use from_env(). Kept for backward compatibility."""
        return cls.from_env()
