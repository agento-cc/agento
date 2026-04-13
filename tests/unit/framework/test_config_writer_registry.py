"""Tests for ConfigWriter protocol, registry, bootstrap discovery, and helpers."""
from __future__ import annotations

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.config_writer import (
    all_owned_paths,
    clear,
    get_agent_config,
    get_config_writer,
    register_config_writer,
)


class _DummyWriter:
    def prepare_workspace(self, working_dir, agent_config, *, agent_view_id=None):
        pass

    def inject_runtime_params(self, artifacts_dir, *, job_id):
        pass

    def owned_paths(self):
        return set(), set()


@pytest.fixture(autouse=True)
def _clean_registry():
    clear()
    yield
    clear()


class TestRegistry:
    def test_register_and_get_roundtrip(self):
        writer = _DummyWriter()
        register_config_writer(AgentProvider.CLAUDE, writer)
        assert get_config_writer(AgentProvider.CLAUDE) is writer

    def test_get_by_string(self):
        writer = _DummyWriter()
        register_config_writer(AgentProvider.CODEX, writer)
        assert get_config_writer("codex") is writer

    def test_missing_provider_raises_key_error(self):
        with pytest.raises(KeyError, match="No ConfigWriter registered"):
            get_config_writer(AgentProvider.CLAUDE)

    def test_invalid_provider_string_raises_value_error(self):
        with pytest.raises(ValueError):
            get_config_writer("unknown_provider")

    def test_clear_resets_registry(self):
        register_config_writer(AgentProvider.CLAUDE, _DummyWriter())
        clear()
        with pytest.raises(KeyError):
            get_config_writer(AgentProvider.CLAUDE)

    def test_overwrite_existing_registration(self):
        writer1 = _DummyWriter()
        writer2 = _DummyWriter()
        register_config_writer(AgentProvider.CLAUDE, writer1)
        register_config_writer(AgentProvider.CLAUDE, writer2)
        assert get_config_writer(AgentProvider.CLAUDE) is writer2


class _WriterWithPaths:
    def __init__(self, files, dirs):
        self._files = files
        self._dirs = dirs

    def prepare_workspace(self, working_dir, agent_config, *, agent_view_id=None):
        pass

    def inject_runtime_params(self, artifacts_dir, *, job_id):
        pass

    def owned_paths(self):
        return self._files, self._dirs


class TestAllOwnedPaths:
    def test_aggregates_across_writers(self):
        register_config_writer(
            AgentProvider.CLAUDE, _WriterWithPaths({".claude.json", ".mcp.json"}, {".claude"}),
        )
        register_config_writer(
            AgentProvider.CODEX, _WriterWithPaths(set(), {".codex"}),
        )
        files, dirs = all_owned_paths()
        assert files == {".claude.json", ".mcp.json"}
        assert dirs == {".claude", ".codex"}

    def test_empty_when_no_writers(self):
        files, dirs = all_owned_paths()
        assert files == set()
        assert dirs == set()


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
