"""Tests for per-job artifacts directory management."""
from pathlib import Path
from unittest.mock import patch

from agento.framework.artifacts_dir import (
    build_artifacts_dir,
    cleanup_artifacts_dir,
    prepare_artifacts_dir,
)


class TestBuildArtifactsDir:
    def test_builds_expected_path(self):
        result = build_artifacts_dir("acme", "developer", 42)
        assert result == Path("/workspace/artifacts/acme/developer/42")

    def test_custom_artifacts_dir(self):
        with patch("agento.framework.artifacts_dir.ARTIFACTS_DIR", "/tmp/rt"):
            result = build_artifacts_dir("acme", "qa", 99)
        assert result == Path("/tmp/rt/acme/qa/99")


class TestPrepareArtifactsDir:
    def test_creates_directory(self, tmp_path):
        artifacts_dir = tmp_path / "acme" / "dev" / "runs" / "1"
        assert not artifacts_dir.exists()
        prepare_artifacts_dir(artifacts_dir)
        assert artifacts_dir.is_dir()

    def test_idempotent(self, tmp_path):
        artifacts_dir = tmp_path / "runs" / "1"
        prepare_artifacts_dir(artifacts_dir)
        prepare_artifacts_dir(artifacts_dir)
        assert artifacts_dir.is_dir()

    def test_cleans_stale_contents_on_retry(self, tmp_path):
        artifacts_dir = tmp_path / "runs" / "1"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "app").symlink_to(tmp_path)
        (artifacts_dir / "leftover.txt").write_text("stale")
        prepare_artifacts_dir(artifacts_dir)
        assert artifacts_dir.is_dir()
        assert not (artifacts_dir / "app").exists()
        assert not (artifacts_dir / "leftover.txt").exists()


class TestCleanupArtifactsDir:
    def test_removes_directory(self, tmp_path):
        artifacts_dir = tmp_path / "runs" / "1"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / ".claude.json").write_text("{}")
        cleanup_artifacts_dir(artifacts_dir)
        assert not artifacts_dir.exists()

    def test_noop_if_missing(self, tmp_path):
        artifacts_dir = tmp_path / "nonexistent"
        cleanup_artifacts_dir(artifacts_dir)  # should not raise

    def test_logs_warning_on_error(self, tmp_path, caplog):
        artifacts_dir = tmp_path / "runs" / "1"
        artifacts_dir.mkdir(parents=True)
        with patch("shutil.rmtree", side_effect=OSError("permission denied")):
            cleanup_artifacts_dir(artifacts_dir)
        assert "Failed to clean up" in caplog.text
