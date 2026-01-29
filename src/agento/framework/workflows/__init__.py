from __future__ import annotations

from ..job_models import AgentType
from .base import Workflow

_WORKFLOW_MAP: dict[AgentType, type[Workflow]] = {}


def get_workflow_class(agent_type: AgentType) -> type[Workflow]:
    cls = _WORKFLOW_MAP.get(agent_type)
    if cls is None:
        raise ValueError(
            f"Unknown workflow type: {agent_type}. "
            f"Registered: {list(_WORKFLOW_MAP.keys())}. Has bootstrap() been called?"
        )
    return cls


def register_workflow(agent_type: AgentType, cls: type[Workflow]) -> None:
    """Register a workflow class for an agent type."""
    _WORKFLOW_MAP[agent_type] = cls


def clear() -> None:
    """Reset registry (for testing)."""
    _WORKFLOW_MAP.clear()
