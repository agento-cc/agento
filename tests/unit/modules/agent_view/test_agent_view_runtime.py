"""Tests for agent_view runtime resolver."""
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from agento.framework.agent_view_runtime import (
    DEFAULT_PRIORITY,
    AgentViewRuntime,
    resolve_agent_view_runtime,
    resolve_publish_priority,
)
from agento.framework.workspace import AgentView, Workspace


def _make_agent_view(id=1, workspace_id=10, code="developer"):
    return AgentView(
        id=id, workspace_id=workspace_id, code=code, label=code.title(),
        is_active=True, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )


def _make_workspace(id=10, code="acme"):
    return Workspace(
        id=id, code=code, label=code.title(),
        is_active=True, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )


class TestResolveAgentViewRuntime:
    def test_none_agent_view_id_returns_defaults(self):
        runtime = resolve_agent_view_runtime(MagicMock(), None)
        assert runtime.agent_view is None
        assert runtime.workspace is None
        assert runtime.priority == DEFAULT_PRIORITY

    @patch("agento.framework.agent_view_runtime.get_agent_view", return_value=None)
    def test_missing_agent_view_returns_defaults(self, mock_get):
        runtime = resolve_agent_view_runtime(MagicMock(), 999)
        assert runtime.agent_view is None

    @patch("agento.framework.agent_view_runtime.build_scoped_overrides")
    @patch("agento.framework.agent_view_runtime.get_workspace")
    @patch("agento.framework.agent_view_runtime.get_agent_view")
    def test_resolves_claude_provider(self, mock_av, mock_ws, mock_overrides):
        mock_av.return_value = _make_agent_view()
        mock_ws.return_value = _make_workspace()
        mock_overrides.return_value = {
            "agent/provider": ("claude", False),
            "agent/claude/model": ("opus-4.6", False),
            "agent/scheduling/priority": ("80", False),
        }

        runtime = resolve_agent_view_runtime(MagicMock(), 1)
        assert runtime.provider == "claude"
        assert runtime.model == "opus-4.6"
        assert runtime.priority == 80
        assert runtime.agent_view is not None
        assert runtime.workspace is not None

    @patch("agento.framework.agent_view_runtime.build_scoped_overrides")
    @patch("agento.framework.agent_view_runtime.get_workspace")
    @patch("agento.framework.agent_view_runtime.get_agent_view")
    def test_resolves_codex_provider(self, mock_av, mock_ws, mock_overrides):
        mock_av.return_value = _make_agent_view()
        mock_ws.return_value = _make_workspace()
        mock_overrides.return_value = {
            "agent/provider": ("codex", False),
            "agent/codex/model": ("gpt-5.4", False),
        }

        runtime = resolve_agent_view_runtime(MagicMock(), 1)
        assert runtime.provider == "codex"
        assert runtime.model == "gpt-5.4"
        assert runtime.priority == DEFAULT_PRIORITY

    @patch("agento.framework.agent_view_runtime.build_scoped_overrides")
    @patch("agento.framework.agent_view_runtime.get_workspace")
    @patch("agento.framework.agent_view_runtime.get_agent_view")
    def test_generic_model_fallback(self, mock_av, mock_ws, mock_overrides):
        mock_av.return_value = _make_agent_view()
        mock_ws.return_value = _make_workspace()
        mock_overrides.return_value = {
            "agent/model": ("sonnet-4.6", False),
        }

        runtime = resolve_agent_view_runtime(MagicMock(), 1)
        assert runtime.provider is None
        assert runtime.model == "sonnet-4.6"

    @patch("agento.framework.agent_view_runtime.build_scoped_overrides")
    @patch("agento.framework.agent_view_runtime.get_workspace")
    @patch("agento.framework.agent_view_runtime.get_agent_view")
    def test_priority_clamped_to_range(self, mock_av, mock_ws, mock_overrides):
        mock_av.return_value = _make_agent_view()
        mock_ws.return_value = _make_workspace()
        mock_overrides.return_value = {
            "agent/scheduling/priority": ("150", False),
        }

        runtime = resolve_agent_view_runtime(MagicMock(), 1)
        assert runtime.priority == 100

    @patch("agento.framework.agent_view_runtime.build_scoped_overrides")
    @patch("agento.framework.agent_view_runtime.get_workspace")
    @patch("agento.framework.agent_view_runtime.get_agent_view")
    def test_invalid_priority_uses_default(self, mock_av, mock_ws, mock_overrides):
        mock_av.return_value = _make_agent_view()
        mock_ws.return_value = _make_workspace()
        mock_overrides.return_value = {
            "agent/scheduling/priority": ("not-a-number", False),
        }

        runtime = resolve_agent_view_runtime(MagicMock(), 1)
        assert runtime.priority == DEFAULT_PRIORITY


class TestResolvePublishPriority:
    def test_none_returns_default(self):
        assert resolve_publish_priority(MagicMock(), None) == DEFAULT_PRIORITY

    @patch("agento.framework.agent_view_runtime.resolve_agent_view_runtime")
    def test_delegates_to_runtime(self, mock_resolve):
        mock_resolve.return_value = AgentViewRuntime(priority=90)
        assert resolve_publish_priority(MagicMock(), 1) == 90
