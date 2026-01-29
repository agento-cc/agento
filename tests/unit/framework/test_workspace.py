"""Tests for workspace and agent_view models."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agento.framework.workspace import (
    AgentView,
    Workspace,
    get_active_agent_views,
    get_agent_view,
    get_agent_view_by_code,
    get_workspace,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0)


@pytest.fixture
def workspace_row(now):
    return {
        "id": 1,
        "code": "main",
        "label": "Main Workspace",
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture
def agent_view_row(now):
    return {
        "id": 10,
        "workspace_id": 1,
        "code": "agent-alpha",
        "label": "Agent Alpha",
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }


class TestWorkspace:
    def test_from_row(self, workspace_row, now):
        ws = Workspace.from_row(workspace_row)
        assert ws.id == 1
        assert ws.code == "main"
        assert ws.label == "Main Workspace"
        assert ws.is_active is True
        assert ws.created_at == now

    def test_from_row_inactive(self, workspace_row):
        workspace_row["is_active"] = 0
        ws = Workspace.from_row(workspace_row)
        assert ws.is_active is False


class TestAgentView:
    def test_from_row(self, agent_view_row, now):
        av = AgentView.from_row(agent_view_row)
        assert av.id == 10
        assert av.workspace_id == 1
        assert av.code == "agent-alpha"
        assert av.label == "Agent Alpha"
        assert av.is_active is True
        assert av.created_at == now

    def test_from_row_inactive(self, agent_view_row):
        agent_view_row["is_active"] = 0
        av = AgentView.from_row(agent_view_row)
        assert av.is_active is False


class TestGetActiveAgentViews:
    def test_returns_active_views(self, agent_view_row):
        cursor = MagicMock()
        cursor.fetchall.return_value = [agent_view_row]
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        views = get_active_agent_views(conn)
        assert len(views) == 1
        assert views[0].code == "agent-alpha"

    def test_returns_empty_list(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        views = get_active_agent_views(conn)
        assert views == []


class TestGetWorkspace:
    def test_found(self, workspace_row):
        cursor = MagicMock()
        cursor.fetchone.return_value = workspace_row
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        ws = get_workspace(conn, 1)
        assert ws is not None
        assert ws.code == "main"

    def test_not_found(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        assert get_workspace(conn, 999) is None


class TestGetAgentView:
    def test_found(self, agent_view_row):
        cursor = MagicMock()
        cursor.fetchone.return_value = agent_view_row
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        av = get_agent_view(conn, 10)
        assert av is not None
        assert av.code == "agent-alpha"

    def test_not_found(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        assert get_agent_view(conn, 999) is None


class TestGetAgentViewByCode:
    def test_found(self, agent_view_row):
        cursor = MagicMock()
        cursor.fetchone.return_value = agent_view_row
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        av = get_agent_view_by_code(conn, "agent-alpha")
        assert av is not None
        assert av.id == 10

    def test_not_found(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        assert get_agent_view_by_code(conn, "nonexistent") is None
