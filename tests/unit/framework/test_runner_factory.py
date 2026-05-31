from __future__ import annotations

from types import SimpleNamespace

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.runner_factory import clear, create_runner, register_runner


def teardown_function():
    clear()


def test_create_runner_passes_token_override_to_modern_factory():
    token = SimpleNamespace(credentials={"api_key": "sk-X"})

    def factory(**kwargs):
        return kwargs

    register_runner(AgentProvider.CODEX, factory)

    runner = create_runner(AgentProvider.CODEX, token_override=token)

    assert runner["token_override"] is token
    assert "credentials_override" not in runner


def test_create_runner_falls_back_to_credentials_override_for_legacy_factory():
    token = SimpleNamespace(credentials={"api_key": "sk-X"})

    def factory(
        *,
        logger=None,
        dry_run=False,
        timeout_seconds=1200,
        model_override=None,
        credentials_override=None,
    ):
        return credentials_override

    register_runner(AgentProvider.CODEX, factory)

    runner = create_runner(AgentProvider.CODEX, token_override=token)

    assert runner == {"api_key": "sk-X"}
