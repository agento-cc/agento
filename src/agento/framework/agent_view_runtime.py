"""Resolve the runtime profile for an agent_view — provider, model, priority, scoped overrides.

Used by the consumer to configure each job's execution environment before dispatch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .scoped_config import build_scoped_overrides
from .workspace import AgentView, Workspace, get_agent_view, get_workspace

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 50


@dataclass
class AgentViewRuntime:
    agent_view: AgentView | None = None
    workspace: Workspace | None = None
    provider: str | None = None
    model: str | None = None
    priority: int = DEFAULT_PRIORITY
    scoped_overrides: dict = field(default_factory=dict)

    def get_value(self, path: str) -> str | None:
        """Get a config value from pre-merged scoped overrides."""
        entry = self.scoped_overrides.get(path)
        if entry is None:
            return None
        value, encrypted = entry
        if encrypted:
            from .encryptor import get_encryptor
            return get_encryptor().decrypt(value)
        return value


def resolve_agent_view_runtime(conn, agent_view_id: int | None) -> AgentViewRuntime:
    """Resolve the full runtime profile for a given agent_view.

    Returns a default runtime if agent_view_id is None or the agent_view is not found.
    """
    if agent_view_id is None:
        return AgentViewRuntime()

    agent_view = get_agent_view(conn, agent_view_id)
    if agent_view is None:
        logger.warning("agent_view_id=%d not found, using defaults", agent_view_id)
        return AgentViewRuntime()

    workspace = get_workspace(conn, agent_view.workspace_id)

    overrides = build_scoped_overrides(
        conn,
        agent_view_id=agent_view.id,
        workspace_id=agent_view.workspace_id,
    )

    runtime = AgentViewRuntime(
        agent_view=agent_view,
        workspace=workspace,
        scoped_overrides=overrides,
    )

    provider = runtime.get_value("agent_view/provider")
    model = runtime.get_value("agent_view/model")

    priority_raw = runtime.get_value("agent_view/scheduling/priority")
    priority = DEFAULT_PRIORITY
    if priority_raw is not None:
        try:
            priority = max(0, min(100, int(priority_raw)))
        except (ValueError, TypeError):
            logger.warning("Invalid agent_view/scheduling/priority=%r, using default", priority_raw)

    runtime.provider = provider
    runtime.model = model
    runtime.priority = priority
    return runtime


def resolve_publish_priority(conn, agent_view_id: int | None) -> int:
    """Resolve the priority for a job being published. Returns DEFAULT_PRIORITY if unset."""
    if agent_view_id is None:
        return DEFAULT_PRIORITY
    runtime = resolve_agent_view_runtime(conn, agent_view_id)
    return runtime.priority
