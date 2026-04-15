"""Tests for workspace_build builder logic."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agento.framework.artifacts_dir import get_current_build_dir
from agento.framework.workspace import AgentView
from agento.modules.workspace_build.src.builder import (
    BuildResult,
    _copy_layer,
    _copy_module_workspaces,
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

    def test_changes_with_different_strategy(self):
        o = {"a/b": ("val", False)}
        assert compute_build_checksum(o, building_strategy="copy") != compute_build_checksum(o, building_strategy="symlink")

    def test_empty_overrides(self):
        assert len(compute_build_checksum({})) == 64

    def test_returns_sha256_hex(self):
        checksum = compute_build_checksum({"x": ("y", False)})
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)


class TestCopyLayer:
    """Tests for the shared _copy_layer helper."""

    def test_copies_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.md").write_text("hello")
        dest = tmp_path / "dest"
        _copy_layer(src, dest)
        assert (dest / "file.md").read_text() == "hello"

    def test_copies_directories(self, tmp_path):
        src = tmp_path / "src"
        (src / "subdir").mkdir(parents=True)
        (src / "subdir" / "deep.md").write_text("deep")
        dest = tmp_path / "dest"
        _copy_layer(src, dest)
        assert (dest / "subdir" / "deep.md").read_text() == "deep"

    def test_skips_underscore_dirs(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "_scope").mkdir()
        (src / "_scope" / "hidden.md").write_text("nope")
        (src / "visible.md").write_text("yes")
        dest = tmp_path / "dest"
        _copy_layer(src, dest)
        assert (dest / "visible.md").exists()
        assert not (dest / "_scope").exists()

    def test_skips_dotfiles(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / ".hidden").write_text("nope")
        (src / "visible.md").write_text("yes")
        dest = tmp_path / "dest"
        _copy_layer(src, dest)
        assert not (dest / ".hidden").exists()
        assert (dest / "visible.md").exists()

    def test_merges_directories(self, tmp_path):
        """dirs_exist_ok=True allows merging into existing dirs."""
        src = tmp_path / "src"
        (src / "subdir").mkdir(parents=True)
        (src / "subdir" / "new.md").write_text("new")
        dest = tmp_path / "dest"
        (dest / "subdir").mkdir(parents=True)
        (dest / "subdir" / "existing.md").write_text("existing")
        _copy_layer(src, dest)
        assert (dest / "subdir" / "existing.md").read_text() == "existing"
        assert (dest / "subdir" / "new.md").read_text() == "new"

    def test_creates_dest_dir(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.md").write_text("hello")
        dest = tmp_path / "nonexistent" / "dest"
        _copy_layer(src, dest)
        assert (dest / "file.md").read_text() == "hello"


class TestCopyTheme:
    """Tests for the flat _copy_theme cascade (THEME_DIR \u2192 _{ws} \u2192 _{ws}/_{av})."""

    def test_base_layer_from_theme_dir(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "SOUL.md").write_text("# Base soul")
        (theme / "app").mkdir()
        (theme / "app" / "data.txt").write_text("base data")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "default", "agent01")
        assert (build / "SOUL.md").read_text() == "# Base soul"
        assert (build / "app" / "data.txt").read_text() == "base data"

    def test_workspace_layer_overrides_base(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "SOUL.md").write_text("# Base soul")
        ws = theme / "_myws"
        ws.mkdir()
        (ws / "SOUL.md").write_text("# Workspace soul")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "myws", "dev01")
        assert (build / "SOUL.md").read_text() == "# Workspace soul"

    def test_agent_view_layer_overrides_workspace(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "SOUL.md").write_text("# Base")
        ws = theme / "_myws"
        ws.mkdir()
        (ws / "SOUL.md").write_text("# Workspace")
        av = ws / "_dev01"
        av.mkdir()
        (av / "SOUL.md").write_text("# Agent view")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "myws", "dev01")
        assert (build / "SOUL.md").read_text() == "# Agent view"

    def test_scope_dirs_not_copied_as_content(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "visible.md").write_text("yes")
        (theme / "_ws1").mkdir()
        (theme / "_ws1" / "scoped.md").write_text("scoped")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "other", "dev")
        assert (build / "visible.md").exists()
        assert not (build / "_ws1").exists()

    def test_base_plus_workspace_no_agent_view(self, tmp_path):
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "base.md").write_text("base")
        ws = theme / "_myws"
        ws.mkdir()
        (ws / "ws.md").write_text("ws extra")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "myws", "nonexistent_av")
        assert (build / "base.md").read_text() == "base"
        assert (build / "ws.md").read_text() == "ws extra"

    def test_directory_merge_across_layers(self, tmp_path):
        """Subdirectories merge rather than replace across layers."""
        theme = tmp_path / "theme"
        (theme / "docs").mkdir(parents=True)
        (theme / "docs" / "base.md").write_text("base doc")
        ws = theme / "_myws"
        (ws / "docs").mkdir(parents=True)
        (ws / "docs" / "ws.md").write_text("ws doc")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "myws", "dev")
        assert (build / "docs" / "base.md").read_text() == "base doc"
        assert (build / "docs" / "ws.md").read_text() == "ws doc"

    def test_dot_prefixed_items_skipped(self, tmp_path):
        """Dot-prefixed items at theme root aren't copied to builds."""
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "included.md").write_text("in")
        (theme / ".hidden").mkdir()
        (theme / ".hidden" / "secret.md").write_text("should not leak")

        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(theme)):
            _copy_theme(build, "default", "agent01")
        assert (build / "included.md").exists()
        assert not (build / ".hidden").exists()

    def test_noop_when_theme_missing(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        with patch(f"{_BUILDER}.THEME_DIR", str(tmp_path / "nonexistent")):
            _copy_theme(build, "default", "agent01")
        assert list(build.iterdir()) == []


class TestCopyModuleWorkspaces:
    """Tests for _copy_module_workspaces with copy, symlink, and layered strategies."""

    def _make_manifest(self, tmp_path, name="testmod"):
        mod_dir = tmp_path / "modules" / name
        ws_dir = mod_dir / "workspace"
        ws_dir.mkdir(parents=True)
        (ws_dir / "README.md").write_text("# Test knowledge")
        (ws_dir / "subdir").mkdir()
        (ws_dir / "subdir" / "deep.md").write_text("deep file")
        manifest = MagicMock()
        manifest.name = name
        manifest.path = str(mod_dir)
        return manifest

    def _make_layered_manifest(self, tmp_path, name="layered_mod"):
        mod_dir = tmp_path / "modules" / name
        ws_dir = mod_dir / "workspace"
        ws_dir.mkdir(parents=True)
        (ws_dir / "base.md").write_text("# Base")
        scope = ws_dir / "_myws"
        scope.mkdir()
        (scope / "ws.md").write_text("# WS scoped")
        av = scope / "_dev01"
        av.mkdir()
        (av / "av.md").write_text("# AV scoped")
        manifest = MagicMock()
        manifest.name = name
        manifest.path = str(mod_dir)
        return manifest

    @patch("agento.framework.bootstrap.get_manifests")
    def test_copy_strategy_copies_files(self, mock_get_manifests, tmp_path):
        manifest = self._make_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "default", "agent01", strategy="copy")

        dest = build_dir / "modules" / "testmod"
        assert dest.is_dir()
        assert not dest.is_symlink()
        assert (dest / "README.md").read_text() == "# Test knowledge"
        assert (dest / "subdir" / "deep.md").read_text() == "deep file"

    @patch("agento.framework.bootstrap.get_manifests")
    def test_symlink_strategy_creates_symlinks(self, mock_get_manifests, tmp_path):
        manifest = self._make_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "default", "agent01", strategy="symlink")

        dest = build_dir / "modules" / "testmod"
        assert dest.is_symlink()
        assert (dest / "README.md").read_text() == "# Test knowledge"
        assert (dest / "subdir" / "deep.md").read_text() == "deep file"

    @patch("agento.framework.bootstrap.get_manifests")
    def test_default_strategy_is_copy(self, mock_get_manifests, tmp_path):
        manifest = self._make_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "default", "agent01")

        dest = build_dir / "modules" / "testmod"
        assert dest.is_dir()
        assert not dest.is_symlink()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_symlink_resolves_to_real_path(self, mock_get_manifests, tmp_path):
        manifest = self._make_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "default", "agent01", strategy="symlink")

        dest = build_dir / "modules" / "testmod"
        # Symlink target should be an absolute resolved path
        target = dest.resolve()
        assert target.is_dir()
        assert not target.is_symlink()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_multiple_modules_symlinked(self, mock_get_manifests, tmp_path):
        m1 = self._make_manifest(tmp_path, "mod_a")
        m2 = self._make_manifest(tmp_path, "mod_b")
        mock_get_manifests.return_value = [m1, m2]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "default", "agent01", strategy="symlink")

        assert (build_dir / "modules" / "mod_a").is_symlink()
        assert (build_dir / "modules" / "mod_b").is_symlink()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_skips_module_without_workspace_dir(self, mock_get_manifests, tmp_path):
        mod_dir = tmp_path / "modules" / "empty_mod"
        mod_dir.mkdir(parents=True)
        manifest = MagicMock()
        manifest.name = "empty_mod"
        manifest.path = str(mod_dir)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "default", "agent01", strategy="symlink")

        assert not (build_dir / "modules" / "empty_mod").exists()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_layered_copy_with_scope_dirs(self, mock_get_manifests, tmp_path):
        """Module with _* dirs applies layered copy: base + workspace + agent_view."""
        manifest = self._make_layered_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "myws", "dev01", strategy="copy")

        dest = build_dir / "modules" / "layered_mod"
        assert (dest / "base.md").read_text() == "# Base"
        assert (dest / "ws.md").read_text() == "# WS scoped"
        assert (dest / "av.md").read_text() == "# AV scoped"
        # Scope dirs must not appear in output
        assert not (dest / "_myws").exists()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_layered_falls_back_to_copy_when_symlink_strategy(self, mock_get_manifests, tmp_path):
        """Symlink strategy falls back to copy when scope dirs exist."""
        manifest = self._make_layered_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "myws", "dev01", strategy="symlink")

        dest = build_dir / "modules" / "layered_mod"
        # Should NOT be a symlink (layered copy used instead)
        assert not dest.is_symlink()
        assert (dest / "base.md").read_text() == "# Base"
        assert (dest / "ws.md").read_text() == "# WS scoped"
        assert (dest / "av.md").read_text() == "# AV scoped"

    @patch("agento.framework.bootstrap.get_manifests")
    def test_layered_workspace_only_no_agent_view(self, mock_get_manifests, tmp_path):
        """When workspace matches but agent_view doesn't, only base + ws layers apply."""
        manifest = self._make_layered_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "myws", "other_av", strategy="copy")

        dest = build_dir / "modules" / "layered_mod"
        assert (dest / "base.md").read_text() == "# Base"
        assert (dest / "ws.md").read_text() == "# WS scoped"
        assert not (dest / "av.md").exists()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_layered_no_matching_workspace(self, mock_get_manifests, tmp_path):
        """When workspace doesn't match, only base layer applies."""
        manifest = self._make_layered_manifest(tmp_path)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "other_ws", "dev01", strategy="copy")

        dest = build_dir / "modules" / "layered_mod"
        assert (dest / "base.md").read_text() == "# Base"
        assert not (dest / "ws.md").exists()
        assert not (dest / "av.md").exists()

    @patch("agento.framework.bootstrap.get_manifests")
    def test_user_module_overlay_merges_via_app_code_path(self, mock_get_manifests, tmp_path):
        """User modules (app/code/*) apply the layered cascade exactly like core modules."""
        # Simulate a manifest whose path lives outside src/agento/modules — i.e. app/code/*.
        mod_dir = tmp_path / "app" / "code" / "mymod"
        ws_dir = mod_dir / "workspace"
        ws_dir.mkdir(parents=True)
        (ws_dir / "README.md").write_text("# base readme")
        scope = ws_dir / "_myws"
        scope.mkdir()
        (scope / "only_in_ws.md").write_text("ws only")
        (scope / "README.md").write_text("# ws readme override")
        av = scope / "_myav"
        av.mkdir()
        (av / "only_av.md").write_text("av only")

        manifest = MagicMock()
        manifest.name = "mymod"
        manifest.path = str(mod_dir)
        mock_get_manifests.return_value = [manifest]

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        _copy_module_workspaces(build_dir, "myws", "myav", strategy="copy")

        dest = build_dir / "modules" / "mymod"
        assert dest.is_dir()
        assert (dest / "README.md").read_text() == "# ws readme override"
        assert (dest / "only_in_ws.md").read_text() == "ws only"
        assert (dest / "only_av.md").read_text() == "av only"
        # Scope dirs must not appear as content.
        assert not (dest / "_myws").exists()


class TestBuildingStrategyFromOverrides:
    """Verify execute_build reads building_strategy from scoped overrides, not global config."""

    @patch("agento.framework.config_writer.get_config_writer")
    @patch("agento.framework.agent_view_runtime.resolve_agent_view_runtime")
    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.framework.workspace.get_agent_view")
    def test_reads_strategy_from_scoped_overrides(
        self, mock_get_av, mock_overrides, mock_resolve, mock_get_writer, tmp_path,
    ):
        """When building_strategy is in scoped overrides, it should be used."""
        mock_get_av.return_value = _make_agent_view()
        mock_overrides.return_value = {
            "agent_view/provider": ("claude", False),
            "workspace_build/building_strategy": ("symlink", False),
        }

        from agento.framework.agent_view_runtime import AgentViewRuntime
        mock_resolve.return_value = AgentViewRuntime(provider="claude")
        mock_get_writer.return_value = MagicMock()

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        call_count = 0
        def fetchone_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"code": "testws"}
            if call_count == 2:
                return None  # No existing build
            return None
        cursor.fetchone.side_effect = fetchone_side_effect
        cursor.lastrowid = 99

        with patch(f"{_BUILDER}.BUILD_DIR", str(tmp_path)):
            result = execute_build(conn, 1)

        assert result.build_id == 99
        assert result.skipped is False
        # Verify a different checksum than without the strategy override
        checksum_copy = compute_build_checksum(
            {"agent_view/provider": ("claude", False), "workspace_build/building_strategy": ("symlink", False)},
            building_strategy="symlink",
        )
        assert result.checksum == checksum_copy


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

    def test_always_writes_claude_md(self, tmp_path):
        _write_instruction_files(tmp_path, {})
        assert "AGENTS.md" in (tmp_path / "CLAUDE.md").read_text()

    def test_skips_empty_override_value(self, tmp_path):
        _write_instruction_files(tmp_path, {"agent_view/instructions/agents_md": ("", False)})
        assert not (tmp_path / "AGENTS.md").exists()

    def test_does_not_overwrite_theme_file_without_db_value(self, tmp_path):
        """When no DB override exists, theme file (already in build_dir) is preserved."""
        (tmp_path / "SOUL.md").write_text("# From theme")
        _write_instruction_files(tmp_path, {})
        assert (tmp_path / "SOUL.md").read_text() == "# From theme"

    def test_db_override_replaces_theme_file(self, tmp_path):
        """DB override takes precedence over file already in build_dir from theme."""
        (tmp_path / "SOUL.md").write_text("# From theme")
        _write_instruction_files(
            tmp_path, {"agent_view/instructions/soul_md": ("# From DB", False)},
        )
        assert (tmp_path / "SOUL.md").read_text() == "# From DB"


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
    def test_skips_existing_build(self, mock_get_av, mock_overrides, tmp_path):
        mock_get_av.return_value = _make_agent_view()
        mock_overrides.return_value = {"agent_view/provider": ("claude", False)}
        existing_dir = tmp_path / "existing_build"
        existing_dir.mkdir()
        existing = {"id": 99, "build_dir": str(existing_dir)}
        conn, _ = self._mock_conn(existing_build=existing)

        result = execute_build(conn, 1)
        assert result.skipped is True
        assert result.build_id == 99

    @patch("agento.framework.config_writer.get_config_writer")
    @patch("agento.framework.agent_view_runtime.resolve_agent_view_runtime")
    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.framework.workspace.get_agent_view")
    def test_rebuilds_when_existing_build_dir_missing_on_disk(
        self, mock_get_av, mock_overrides, mock_resolve, mock_get_writer, tmp_path,
    ):
        """If DB says ready but build_dir was deleted manually, rebuild instead of lying."""
        mock_get_av.return_value = _make_agent_view()
        mock_overrides.return_value = {"agent_view/provider": ("claude", False)}
        from agento.framework.agent_view_runtime import AgentViewRuntime
        mock_resolve.return_value = AgentViewRuntime(provider="claude")
        mock_get_writer.return_value = MagicMock()

        missing_dir = tmp_path / "deleted_by_user"
        assert not missing_dir.exists()
        existing = {"id": 99, "build_dir": str(missing_dir)}
        conn, cursor = self._mock_conn(existing_build=existing)

        with patch(f"{_BUILDER}.BUILD_DIR", str(tmp_path)):
            result = execute_build(conn, 1)

        assert result.skipped is False
        assert result.build_id == 42
        # Stale DB record was invalidated to 'failed'
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE workspace_build SET status = 'failed'" in c.args[0]
            and c.args[1] == (99,)
        ]
        assert update_calls, "Expected stale build 99 to be marked failed"

    @patch("agento.framework.config_writer.get_config_writer")
    @patch("agento.framework.agent_view_runtime.resolve_agent_view_runtime")
    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.framework.workspace.get_agent_view")
    def test_force_bypasses_skip_and_cleans_prior_build(
        self, mock_get_av, mock_overrides, mock_resolve, mock_get_writer, tmp_path,
    ):
        """force=True: rebuild even when checksum matches and prior dir is intact."""
        mock_get_av.return_value = _make_agent_view()
        mock_overrides.return_value = {"agent_view/provider": ("claude", False)}
        from agento.framework.agent_view_runtime import AgentViewRuntime
        mock_resolve.return_value = AgentViewRuntime(provider="claude")
        mock_get_writer.return_value = MagicMock()

        existing_dir = tmp_path / "prior_build"
        existing_dir.mkdir()
        (existing_dir / "sentinel.txt").write_text("should be wiped")
        existing = {"id": 99, "build_dir": str(existing_dir)}
        conn, cursor = self._mock_conn(existing_build=existing)

        with patch(f"{_BUILDER}.BUILD_DIR", str(tmp_path)):
            result = execute_build(conn, 1, force=True)

        assert result.skipped is False
        assert result.build_id == 42  # new lastrowid, not the stale 99
        # Prior on-disk dir was cleaned up before the rebuild.
        assert not existing_dir.exists()
        # Stale DB record was retired.
        update_calls = [
            c for c in cursor.execute.call_args_list
            if "UPDATE workspace_build SET status = 'failed'" in c.args[0]
            and c.args[1] == (99,)
        ]
        assert update_calls, "Expected prior build 99 to be marked failed under --force"

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


class TestValidateCode:
    """Tests for workspace/agent_view code validation."""

    def test_valid_codes(self):
        from agento.framework.workspace import validate_code
        for code in ("default", "agent01", "kazar_dev", "my_workspace", "a"):
            validate_code(code)  # should not raise

    def test_rejects_underscore_prefix(self):
        from agento.framework.workspace import validate_code
        with pytest.raises(ValueError, match="must match"):
            validate_code("_hidden")

    def test_rejects_dot_prefix(self):
        from agento.framework.workspace import validate_code
        with pytest.raises(ValueError, match="must match"):
            validate_code(".dotted")

    def test_rejects_uppercase(self):
        from agento.framework.workspace import validate_code
        with pytest.raises(ValueError, match="must match"):
            validate_code("MyWorkspace")

    def test_rejects_empty(self):
        from agento.framework.workspace import validate_code
        with pytest.raises(ValueError, match="must match"):
            validate_code("")

    def test_rejects_starts_with_digit(self):
        from agento.framework.workspace import validate_code
        with pytest.raises(ValueError, match="must match"):
            validate_code("1abc")
