"""Tests for workspace_build builder logic."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.artifacts_dir import get_current_build_dir
from agento.framework.workspace import AgentView
from agento.modules.workspace_build.src.builder import (
    BuildResult,
    _copy_theme,
    _write_instruction_files,
    compute_build_checksum,
    execute_build,
)

_BUILDER = "agento.modules.workspace_build.src.builder"


def _make_agent_view(**overrides):
    defaults = dict(
        id=1, workspace_id=10, code="dev", label="Developer",
        is_active=True, created_at=datetime.now(), updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return AgentView(**defaults)


class TestComputeBuildChecksum:
    def test_deterministic(self):
        overrides = {"a/b": ("val1", False), "c/d": ("val2", False)}
        assert compute_build_checksum(overrides) == compute_build_checksum(overrides)

    def test_changes_with_different_values(self):
        assert compute_build_checksum({"a/b": ("val1", False)}) != compute_build_checksum({"a/b": ("val2", False)})

    def test_changes_with_different_keys(self):
        assert compute_build_checksum({"a/b": ("v", False)}) != compute_build_checksum({"x/y": ("v", False)})

    def test_includes_skill_checksums(self):
        o = {"a/b": ("val", False)}
        assert compute_build_checksum(o) != compute_build_checksum(o, skill_checksums=["abc123"])

    def test_skill_order_irrelevant(self):
        o = {"a/b": ("val", False)}
        assert (
            compute_build_checksum(o, skill_checksums=["aaa", "bbb"])
            == compute_build_checksum(o, skill_checksums=["bbb", "aaa"])
        )

    def test_empty_overrides(self):
        assert len(compute_build_checksum({})) == 64

    def test_returns_sha256_hex(self):
        checksum = compute_build_checksum({"x": ("y", False)})
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)


class TestWriteInstructionFiles:
    def test_writes_from_overrides(self, tmp_path):
        overrides = {
            "agent_view/instructions/agents_md": ("# My agents instructions", False),
            "agent_view/instructions/soul_md": ("# Soul content", False),
        }
        _write_instruction_files(tmp_path, overrides)
        assert (tmp_path / "AGENTS.md").read_text() == "# My agents instructions"
        assert (tmp_path / "SOUL.md").read_text() == "# Soul content"
        assert (tmp_path / "CLAUDE.md").exists()

    def test_falls_back_to_workspace_files(self, tmp_path):
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / "AGENTS.md").write_text("# Workspace agents")
        (ws_dir / "SOUL.md").write_text("# Workspace soul")

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _write_instruction_files(build_dir, {}, workspace_dir=str(ws_dir))
        assert (build_dir / "AGENTS.md").read_text() == "# Workspace agents"
        assert (build_dir / "SOUL.md").read_text() == "# Workspace soul"

    def test_always_writes_claude_md(self, tmp_path):
        _write_instruction_files(tmp_path, {})
        assert "AGENTS.md" in (tmp_path / "CLAUDE.md").read_text()

    def test_skips_empty_override_value(self, tmp_path):
        _write_instruction_files(tmp_path, {"agent_view/instructions/agents_md": ("", False)})
        assert not (tmp_path / "AGENTS.md").exists()

    def test_override_takes_precedence_over_workspace(self, tmp_path):
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / "AGENTS.md").write_text("# From workspace")

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _write_instruction_files(build_dir, {"agent_view/instructions/agents_md": ("# From DB", False)}, workspace_dir=str(ws_dir))
        assert (build_dir / "AGENTS.md").read_text() == "# From DB"


class TestCopyTheme:
    def test_copies_files_from_theme(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "SOUL.md").write_text("# Theme soul")
        (theme / "KnowledgeBase").mkdir()
        (theme / "KnowledgeBase" / "info.md").write_text("# Info")

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build_dir)

        assert (build_dir / "SOUL.md").read_text() == "# Theme soul"
        assert (build_dir / "KnowledgeBase" / "info.md").read_text() == "# Info"

    def test_skips_dotfiles(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / ".gitignore").write_text("*.log")
        (theme / "README.md").write_text("# Readme")

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build_dir)

        assert not (build_dir / ".gitignore").exists()
        assert (build_dir / "README.md").exists()

    def test_noop_when_theme_missing(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        with patch(f"{_BUILDER}.THEME_DIR", str(tmp_path / "nonexistent")):
            _copy_theme(build_dir)

        assert list(build_dir.iterdir()) == []


class TestGetCurrentBuildDir:
    _ARTIFACTS_DIR = "agento.framework.artifacts_dir"

    def test_returns_none_when_no_symlink(self, tmp_path):
        with patch(f"{self._ARTIFACTS_DIR}.BUILD_DIR", str(tmp_path)):
            assert get_current_build_dir("ws", "av") is None

    def test_returns_path_when_symlink_exists(self, tmp_path):
        build_dir = tmp_path / "ws" / "av" / "builds" / "1"
        build_dir.mkdir(parents=True)
        (tmp_path / "ws" / "av" / "current").symlink_to(build_dir)

        with patch(f"{self._ARTIFACTS_DIR}.BUILD_DIR", str(tmp_path)):
            result = get_current_build_dir("ws", "av")
            assert result is not None
            assert result.is_dir()

    def test_returns_none_when_symlink_target_missing(self, tmp_path):
        link_parent = tmp_path / "ws" / "av"
        link_parent.mkdir(parents=True)
        (link_parent / "current").symlink_to(link_parent / "builds" / "999")

        with patch(f"{self._ARTIFACTS_DIR}.BUILD_DIR", str(tmp_path)):
            assert get_current_build_dir("ws", "av") is None


class TestExecuteBuild:
    def _mock_conn(self, *, ws_code="testws", existing_build=None):
        """Create a mock DB connection with cursor context manager."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        call_count = 0
        def fetchone_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"code": ws_code}
            if call_count == 2:
                return existing_build
            return None

        cursor.fetchone.side_effect = fetchone_side_effect
        cursor.lastrowid = 42
        return conn, cursor

    @patch("agento.framework.config_writer.get_config_writer")
    @patch("agento.framework.agent_view_runtime.resolve_agent_view_runtime")
    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.framework.workspace.get_agent_view")
    def test_full_build_flow(self, mock_get_av, mock_overrides, mock_resolve, mock_get_writer, tmp_path):
        mock_get_av.return_value = _make_agent_view()
        mock_overrides.return_value = {"agent_view/provider": ("claude", False)}

        from agento.framework.agent_view_runtime import AgentViewRuntime
        mock_resolve.return_value = AgentViewRuntime(provider="claude")
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        conn, _ = self._mock_conn()

        with patch(f"{_BUILDER}.BUILD_DIR", str(tmp_path)):
            result = execute_build(conn, 1)

        assert isinstance(result, BuildResult)
        assert result.build_id == 42
        assert result.skipped is False
        assert len(result.checksum) == 64
        mock_get_writer.assert_called_once_with("claude")
        conn.commit.assert_called()

    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.framework.workspace.get_agent_view")
    def test_skips_existing_build(self, mock_get_av, mock_overrides):
        mock_get_av.return_value = _make_agent_view()
        mock_overrides.return_value = {"agent_view/provider": ("claude", False)}
        existing = {"id": 99, "build_dir": "/workspace/ws/dev/builds/99"}
        conn, _ = self._mock_conn(existing_build=existing)

        result = execute_build(conn, 1)
        assert result.skipped is True
        assert result.build_id == 99

    @patch("agento.framework.workspace.get_agent_view")
    def test_raises_on_missing_agent_view(self, mock_get_av):
        mock_get_av.return_value = None
        with pytest.raises(ValueError, match="agent_view 999 not found"):
            execute_build(MagicMock(), 999)

    @patch("agento.framework.workspace.get_agent_view")
    def test_raises_on_missing_workspace(self, mock_get_av):
        mock_get_av.return_value = _make_agent_view()
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None

        with pytest.raises(ValueError, match="workspace 10 not found"):
            execute_build(conn, 1)
