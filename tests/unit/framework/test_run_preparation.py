"""Tests for the shared pre-spawn pipeline used by the consumer and by
the ``agento run`` path: freshness check, artifacts dir, and build copy.

Mirrors the inline block in ``consumer._run_job`` (lines 453-486) so the
extraction is behavior-preserving.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.events import WorkspaceBuildCheckEvent


@dataclass
class _AV:
    code: str
    id: int


@dataclass
class _WS:
    code: str
    id: int


@dataclass
class _Runtime:
    agent_view: _AV | None
    workspace: _WS | None
    provider: str | None


class TestMaterializeRunWorkspace:
    def test_returns_none_when_no_agent_view(self):
        from agento.framework.run_preparation import materialize_run_workspace
        runtime = _Runtime(agent_view=None, workspace=None, provider="claude")
        em = MagicMock()
        home, working = materialize_run_workspace(runtime, run_id=1, em=em)
        assert home is None and working is None
        em.dispatch.assert_not_called()

    def test_dispatches_freshness_check(self, tmp_path):
        from agento.framework.run_preparation import materialize_run_workspace
        runtime = _Runtime(
            agent_view=_AV(code="dev", id=7),
            workspace=_WS(code="acme", id=3),
            provider=None,  # no provider → no copy, but freshness still dispatched
        )
        em = MagicMock()
        with patch("agento.framework.artifacts_dir.ARTIFACTS_DIR", str(tmp_path / "artifacts")), \
             patch("agento.framework.artifacts_dir.BUILD_DIR", str(tmp_path / "build")):
            materialize_run_workspace(runtime, run_id=1, em=em)

        assert em.dispatch.called
        name, payload = em.dispatch.call_args.args
        assert name == "workspace_build_check_before"
        assert isinstance(payload, WorkspaceBuildCheckEvent)
        assert payload.agent_view_id == 7

    def test_reraises_event_error(self, tmp_path):
        from agento.framework.run_preparation import materialize_run_workspace
        runtime = _Runtime(
            agent_view=_AV(code="dev", id=7),
            workspace=_WS(code="acme", id=3),
            provider="claude",
        )

        class _Boom(RuntimeError):
            pass

        def _set_error(_name, event):
            event.error = _Boom("rebuild failed")

        em = MagicMock()
        em.dispatch.side_effect = _set_error

        with patch("agento.framework.artifacts_dir.ARTIFACTS_DIR", str(tmp_path / "artifacts")), \
             patch("agento.framework.artifacts_dir.BUILD_DIR", str(tmp_path / "build")), \
             pytest.raises(_Boom, match="rebuild failed"):
            materialize_run_workspace(runtime, run_id=1, em=em)

    def test_returns_paths_and_copies_build(self, tmp_path):
        from agento.framework.run_preparation import materialize_run_workspace
        # Stage a "current" build dir the function can resolve.
        ws, av = "acme", "dev"
        build_root = tmp_path / "build"
        actual_build = build_root / ws / av / "20250101-000000"
        actual_build.mkdir(parents=True)
        (actual_build / "AGENTS.md").write_text("hello")
        current_link = build_root / ws / av / "current"
        current_link.symlink_to(actual_build)

        runtime = _Runtime(
            agent_view=_AV(code=av, id=7),
            workspace=_WS(code=ws, id=3),
            provider=None,  # skip ConfigWriter injection
        )
        em = MagicMock()

        with patch("agento.framework.artifacts_dir.ARTIFACTS_DIR", str(tmp_path / "artifacts")), \
             patch("agento.framework.artifacts_dir.BUILD_DIR", str(tmp_path / "build")):
            home, working = materialize_run_workspace(runtime, run_id="run", em=em)

        assert home == actual_build
        assert working == tmp_path / "artifacts" / ws / av / "run"
        assert working.is_dir()
        # Universal file should have been copied (not symlinked)
        assert (working / "AGENTS.md").is_file()
        assert not (working / "AGENTS.md").is_symlink()
