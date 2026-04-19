"""Helpers for interpreting showIn* scope-restriction flags on system.json fields.

Magento-style: fields can declare `showInDefault` / `showInWorkspace` /
`showInAgentView` booleans to restrict which scopes allow editing. Missing
flags default to True (backward compatible — field editable at any scope).
"""
from __future__ import annotations

from .scoped_config import Scope

_SCOPE_TO_FLAG: dict[str, str] = {
    Scope.DEFAULT: "showInDefault",
    Scope.WORKSPACE: "showInWorkspace",
    Scope.AGENT_VIEW: "showInAgentView",
}


def is_scope_allowed(field_schema: dict, scope: str) -> bool:
    """Return True if the field may be edited at the given scope."""
    flag = _SCOPE_TO_FLAG.get(scope)
    if flag is None:
        return True
    return bool(field_schema.get(flag, True))


def allowed_scopes(field_schema: dict) -> list[str]:
    """Return scopes where the field is editable, in default→workspace→agent_view order."""
    return [
        scope
        for scope, flag in _SCOPE_TO_FLAG.items()
        if bool(field_schema.get(flag, True))
    ]
