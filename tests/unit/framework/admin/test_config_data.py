"""Tests for admin data layer: scope-restriction flags propagated to ResolvedField."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agento.framework.admin.data import (
    ModuleSchema,
    ResolvedField,
    get_resolved_fields,
)
from agento.framework.scoped_config import Scope


def _make_schema(
    fields: dict | None = None,
    tools: dict | None = None,
) -> ModuleSchema:
    return ModuleSchema(
        name="testmod",
        fields=fields or {},
        tools=tools or {},
        module_path=None,
    )


class TestResolvedFieldScopeFlags:
    def test_field_with_global_only_flag_at_agent_view_not_editable(self):
        schema = _make_schema(fields={
            "timezone": {
                "type": "string",
                "label": "TZ",
                "showInDefault": True,
                "showInWorkspace": False,
                "showInAgentView": False,
            }
        })
        with patch(
            "agento.framework.admin.data.get_module_schemas", return_value=[schema]
        ), patch(
            "agento.framework.admin.data.read_config_defaults", return_value={}
        ), patch(
            "agento.framework.admin.data.build_scoped_overrides", return_value={}
        ), patch(
            "agento.framework.admin.data.load_scoped_db_overrides", return_value={}
        ):
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = {"workspace_id": 1}
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

            fields = get_resolved_fields(conn, "testmod", Scope.AGENT_VIEW, 42)

        assert len(fields) == 1
        f = fields[0]
        assert f.editable_at_scope is False
        assert f.allowed_scopes == [Scope.DEFAULT]
        assert "[readonly]" in f.display_value

    def test_field_editable_at_default_when_global_only(self):
        schema = _make_schema(fields={
            "timezone": {
                "type": "string",
                "label": "TZ",
                "showInDefault": True,
                "showInWorkspace": False,
                "showInAgentView": False,
            }
        })
        with patch(
            "agento.framework.admin.data.get_module_schemas", return_value=[schema]
        ), patch(
            "agento.framework.admin.data.read_config_defaults", return_value={}
        ), patch(
            "agento.framework.admin.data.load_db_overrides", return_value={}
        ):
            fields = get_resolved_fields(None, "testmod", Scope.DEFAULT, 0)

        assert len(fields) == 1
        f = fields[0]
        assert f.editable_at_scope is True
        assert "[readonly]" not in f.display_value

    def test_field_without_flags_editable_everywhere(self):
        schema = _make_schema(fields={
            "model": {"type": "string", "label": "Model"}
        })
        with patch(
            "agento.framework.admin.data.get_module_schemas", return_value=[schema]
        ), patch(
            "agento.framework.admin.data.read_config_defaults", return_value={}
        ), patch(
            "agento.framework.admin.data.build_scoped_overrides", return_value={}
        ), patch(
            "agento.framework.admin.data.load_scoped_db_overrides", return_value={}
        ):
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = {"workspace_id": 1}
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

            fields = get_resolved_fields(conn, "testmod", Scope.AGENT_VIEW, 42)

        assert len(fields) == 1
        f = fields[0]
        assert f.editable_at_scope is True
        assert f.allowed_scopes == [Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW]

    def test_tool_field_scope_restriction_applied(self):
        schema = _make_schema(tools={
            "mytool": {
                "api_key": {
                    "type": "string",
                    "label": "API Key",
                    "showInDefault": True,
                    "showInWorkspace": False,
                    "showInAgentView": False,
                }
            }
        })
        with patch(
            "agento.framework.admin.data.get_module_schemas", return_value=[schema]
        ), patch(
            "agento.framework.admin.data.read_config_defaults", return_value={}
        ), patch(
            "agento.framework.admin.data.build_scoped_overrides", return_value={}
        ), patch(
            "agento.framework.admin.data.load_scoped_db_overrides", return_value={}
        ):
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = {"workspace_id": 1}
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

            fields = get_resolved_fields(conn, "testmod", Scope.AGENT_VIEW, 42)

        assert len(fields) == 1
        f = fields[0]
        assert f.path == "testmod/tools/mytool/api_key"
        assert f.editable_at_scope is False
        assert f.allowed_scopes == [Scope.DEFAULT]
        assert "[readonly]" in f.display_value

    def test_display_value_global_suffix_on_existing_value(self):
        schema = _make_schema(fields={
            "timezone": {
                "type": "string",
                "label": "TZ",
                "showInDefault": True,
                "showInWorkspace": False,
                "showInAgentView": False,
            }
        })
        overrides = {"testmod/timezone": ("UTC", False)}
        with patch(
            "agento.framework.admin.data.get_module_schemas", return_value=[schema]
        ), patch(
            "agento.framework.admin.data.read_config_defaults", return_value={}
        ), patch(
            "agento.framework.admin.data.build_scoped_overrides", return_value=overrides
        ), patch(
            "agento.framework.admin.data.load_scoped_db_overrides", return_value={}
        ):
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = {"workspace_id": 1}
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

            fields = get_resolved_fields(conn, "testmod", Scope.AGENT_VIEW, 42)

        assert len(fields) == 1
        assert fields[0].display_value == "UTC [readonly]"
        assert fields[0].editable_at_scope is False


class TestResolvedFieldDefaults:
    def test_default_editable_and_allowed_scopes(self):
        field = ResolvedField(
            path="m/f", field_name="f", value=None, display_value="",
            source="none", field_type="string", label="", obscure=False,
        )
        assert field.editable_at_scope is True
        assert field.allowed_scopes == [Scope.DEFAULT, Scope.WORKSPACE, Scope.AGENT_VIEW]
