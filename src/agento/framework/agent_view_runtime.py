"""Resolve the runtime profile for an agent_view — provider, model, priority, scoped overrides.

Used by the consumer to configure each job's execution environment before dispatch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config_resolver import ScopedConfigService
from .scoped_config import Scope
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


def resolve_agent_view_runtime(conn, agent_view_id: int | None) -> AgentViewRuntime:
    """Resolve the full runtime profile for a given agent_view.

    Resolution goes through the single ``ScopedConfigService`` (ENV -> scoped DB ->
    config.json), so ``CONFIG__AGENT_VIEW__PROVIDER`` / ``__MODEL`` /
    ``__SCHEDULING__PRIORITY`` env overrides are honored.

    When ``agent_view_id`` is None (or the row is not found) the runtime resolves
    at the global (default) scope so agent-view-less jobs (e.g. blank-source
    tests, single-tenant deployments that run before any agent_view is created)
    still know which provider pool to select from.
    """
    agent_view = get_agent_view(conn, agent_view_id) if agent_view_id is not None else None
    if agent_view_id is not None and agent_view is None:
        logger.warning("agent_view_id=%d not found, falling back to global config", agent_view_id)

    workspace = (
        get_workspace(conn, agent_view.workspace_id) if agent_view is not None else None
    )

    if agent_view is not None:
        svc = ScopedConfigService(
            conn, Scope.AGENT_VIEW, agent_view.id, workspace_id=agent_view.workspace_id,
        )
    else:
        svc = ScopedConfigService(conn, Scope.DEFAULT, 0)

    runtime = AgentViewRuntime(
        agent_view=agent_view,
        workspace=workspace,
        scoped_overrides=svc.overrides,
    )

    priority_raw = svc.get("agent_view/scheduling/priority")
    priority = DEFAULT_PRIORITY
    if priority_raw is not None:
        try:
            priority = max(0, min(100, int(priority_raw)))
        except (ValueError, TypeError):
            logger.warning("Invalid agent_view/scheduling/priority=%r, using default", priority_raw)

    runtime.provider = svc.get("agent_view/provider")
    runtime.model = svc.get("agent_view/model")
    runtime.priority = priority
    return runtime


def resolve_publish_priority(conn, agent_view_id: int | None) -> int:
    """Resolve the priority for a job being published. Returns DEFAULT_PRIORITY if unset."""
    if agent_view_id is None:
        return DEFAULT_PRIORITY
    runtime = resolve_agent_view_runtime(conn, agent_view_id)
    return runtime.priority
