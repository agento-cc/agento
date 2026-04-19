"""Tests for config_schema helpers (scope restriction flags)."""
from __future__ import annotations

from agento.framework.config_schema import allowed_scopes, is_scope_allowed
from agento.framework.scoped_config import Scope


class TestIsScopeAllowed:
    def test_missing_flags_allow_all_scopes(self):
        schema = {"type": "string", "label": "foo"}
        assert is_scope_allowed(schema, Scope.DEFAULT) is True
        assert is_scope_allowed(schema, Scope.WORKSPACE) is True
        assert is_scope_allowed(schema, Scope.AGENT_VIEW) is True

    def test_respects_show_in_agent_view_false(self):
        schema = {
            "type": "string",
            "showInDefault": True,
            "showInWorkspace": False,
            "showInAgentView": False,
        }
        assert is_scope_allowed(schema, Scope.DEFAULT) is True
        assert is_scope_allowed(schema, Scope.WORKSPACE) is False
        assert is_scope_allowed(schema, Scope.AGENT_VIEW) is False

    def test_partial_flags_default_missing_to_true(self):
        schema = {"showInAgentView": False}
        assert is_scope_allowed(schema, Scope.DEFAULT) is True
        assert is_scope_allowed(schema, Scope.WORKSPACE) is True
        assert is_scope_allowed(schema, Scope.AGENT_VIEW) is False

    def test_unknown_scope_returns_true(self):
        schema = {"showInDefault": False}
        assert is_scope_allowed(schema, "mystery") is True

    def test_explicit_true_for_scope(self):
        schema = {"showInDefault": True}
        assert is_scope_allowed(schema, Scope.DEFAULT) is True


class TestAllowedScopes:
    def test_missing_flags_returns_all_three(self):
        assert allowed_scopes({}) == [Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW]

    def test_returns_only_permitted_scopes_in_order(self):
        schema = {
            "showInDefault": True,
            "showInWorkspace": False,
            "showInAgentView": False,
        }
        assert allowed_scopes(schema) == [Scope.DEFAULT]

    def test_returns_empty_list_when_all_false(self):
        schema = {
            "showInDefault": False,
            "showInWorkspace": False,
            "showInAgentView": False,
        }
        assert allowed_scopes(schema) == []

    def test_order_is_default_workspace_agent_view(self):
        schema = {
            "showInDefault": True,
            "showInWorkspace": True,
            "showInAgentView": True,
        }
        assert allowed_scopes(schema) == [Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW]
