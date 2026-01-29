"""Tests for per-run directory management."""
from pathlib import Path
from unittest.mock import patch

from agento.framework.run_dir import build_run_dir, cleanup_run_dir, prepare_run_dir


class TestBuildRunDir:
    def test_builds_expected_path(self):
        result = build_run_dir("acme", "developer", 42)
        assert result == Path("/workspace/acme/developer/runs/42")

    def test_custom_base_dir(self):
        with patch("agento.framework.run_dir.BASE_WORKSPACE_DIR", "/tmp/ws"):
            result = build_run_dir("acme", "qa", 99)
        assert result == Path("/tmp/ws/acme/qa/runs/99")


class TestPrepareRunDir:
    def test_creates_directory(self, tmp_path):
        run_dir = tmp_path / "acme" / "dev" / "runs" / "1"
        assert not run_dir.exists()
        prepare_run_dir(run_dir)
        assert run_dir.is_dir()

    def test_idempotent(self, tmp_path):
        run_dir = tmp_path / "runs" / "1"
        prepare_run_dir(run_dir)
        prepare_run_dir(run_dir)
        assert run_dir.is_dir()


class TestCleanupRunDir:
    def test_removes_directory(self, tmp_path):
        run_dir = tmp_path / "runs" / "1"
        run_dir.mkdir(parents=True)
        (run_dir / ".claude.json").write_text("{}")
        cleanup_run_dir(run_dir)
        assert not run_dir.exists()

    def test_noop_if_missing(self, tmp_path):
        run_dir = tmp_path / "nonexistent"
        cleanup_run_dir(run_dir)  # should not raise

    def test_logs_warning_on_error(self, tmp_path, caplog):
        run_dir = tmp_path / "runs" / "1"
        run_dir.mkdir(parents=True)
        with patch("shutil.rmtree", side_effect=OSError("permission denied")):
            cleanup_run_dir(run_dir)
        assert "Failed to clean up" in caplog.text
