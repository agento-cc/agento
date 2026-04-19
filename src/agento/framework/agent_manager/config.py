from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentManagerConfig:
    usage_window_hours: int = 24
    rotation_interval_hours: int = 1

    @classmethod
    def from_env(cls) -> AgentManagerConfig:
        """Build from env vars only."""
        return cls(
            usage_window_hours=int(os.environ.get("AGENT_USAGE_WINDOW_HOURS", "24")),
            rotation_interval_hours=int(os.environ.get("AGENT_ROTATION_INTERVAL_HOURS", "1")),
        )
