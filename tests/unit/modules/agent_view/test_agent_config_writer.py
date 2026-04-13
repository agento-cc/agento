"""Tests for get_agent_config helper (framework config_writer module)."""
from __future__ import annotations

from agento.framework.config_writer import get_agent_config


class TestGetAgentConfig:
    def test_extracts_agent_prefix(self):
        overrides = {
            "agent_view/model": ("opus-4", False),
            "agent_view/mcp/servers": ('{"toolbox": {}}', False),
            "jira/token": ("abc", False),
        }
        result = get_agent_config(overrides)
        assert result == {
            "model": "opus-4",
            "mcp/servers": '{"toolbox": {}}',
        }

    def test_skips_none_values(self):
        overrides = {"agent_view/model": (None, False)}
        assert get_agent_config(overrides) == {}

    def test_empty_overrides(self):
        assert get_agent_config({}) == {}
