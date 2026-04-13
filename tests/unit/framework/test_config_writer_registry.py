"""Tests for ConfigWriter protocol, registry, and bootstrap discovery."""
from __future__ import annotations

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.config_writer import (
    clear,
    get_config_writer,
    register_config_writer,
)


class _DummyWriter:
    def prepare_workspace(self, working_dir, agent_config, *, agent_view_id=None):
        pass

    def inject_runtime_params(self, run_dir, *, job_id, workspace_code, agent_view_code):
        pass


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
