"""Tests for consumer integration with workspace_build (via framework run_dir)."""
from __future__ import annotations

from unittest.mock import patch

from agento.framework.run_dir import copy_build_to_run_dir, get_current_build_dir


class TestGetCurrentBuildDir:
    def test_returns_none_when_no_symlink(self, tmp_path):
        with patch("agento.framework.run_dir.BASE_WORKSPACE_DIR", str(tmp_path)):
            assert get_current_build_dir("ws", "av") is None

    def test_returns_path_when_symlink_exists(self, tmp_path):
        build_dir = tmp_path / "ws" / "av" / "builds" / "1"
        build_dir.mkdir(parents=True)
        (tmp_path / "ws" / "av" / "current").symlink_to(build_dir)

        with patch("agento.framework.run_dir.BASE_WORKSPACE_DIR", str(tmp_path)):
            result = get_current_build_dir("ws", "av")
            assert result is not None
            assert result.is_dir()

    def test_returns_none_when_symlink_target_missing(self, tmp_path):
        link_parent = tmp_path / "ws" / "av"
        link_parent.mkdir(parents=True)
        (link_parent / "current").symlink_to(link_parent / "builds" / "999")

        with patch("agento.framework.run_dir.BASE_WORKSPACE_DIR", str(tmp_path)):
            assert get_current_build_dir("ws", "av") is None


class TestCopyBuildToRunDir:
    def test_copies_files(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "CLAUDE.md").write_text("# Test")
        (build_dir / "AGENTS.md").write_text("# Agents")

        run_dir = tmp_path / "run"
        run_dir.mkdir()

        copy_build_to_run_dir(build_dir, run_dir)

        assert (run_dir / "CLAUDE.md").read_text() == "# Test"
        assert (run_dir / "AGENTS.md").read_text() == "# Agents"

    def test_copies_directories(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        subdir = build_dir / ".claude" / "skills"
        subdir.mkdir(parents=True)
        (subdir / "test.md").write_text("# Skill")

        run_dir = tmp_path / "run"
        run_dir.mkdir()

        copy_build_to_run_dir(build_dir, run_dir)

        assert (run_dir / ".claude" / "skills" / "test.md").read_text() == "# Skill"

    def test_handles_empty_build_dir(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        copy_build_to_run_dir(build_dir, run_dir)
        assert list(run_dir.iterdir()) == []
