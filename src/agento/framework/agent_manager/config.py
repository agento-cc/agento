from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentManagerConfig:
    tokens_dir: str = "/etc/tokens"
    active_dir: str = "/etc/tokens/active"
    usage_window_hours: int = 24
    rotation_interval_hours: int = 1

    @classmethod
    def from_env(cls) -> AgentManagerConfig:
        """Build from env vars only."""
        return cls(
            tokens_dir=os.environ.get("AGENT_TOKENS_DIR", "/etc/tokens"),
            active_dir=os.environ.get("AGENT_ACTIVE_DIR", "/etc/tokens/active"),
            usage_window_hours=int(os.environ.get("AGENT_USAGE_WINDOW_HOURS", "24")),
            rotation_interval_hours=int(os.environ.get("AGENT_ROTATION_INTERVAL_HOURS", "1")),
        )
