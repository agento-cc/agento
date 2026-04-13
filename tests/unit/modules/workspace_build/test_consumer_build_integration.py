"""Tests for consumer integration with workspace_build (via framework artifacts_dir)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agento.framework.agent_manager.models import AgentProvider
from agento.framework.artifacts_dir import copy_build_to_artifacts_dir, get_current_build_dir
from agento.framework.config_writer import clear, register_config_writer
from agento.modules.claude.src.config import ClaudeConfigWriter
from agento.modules.codex.src.config import CodexConfigWriter


@pytest.fixture
def with_writers():
    """Register Claude + Codex writers so framework knows which paths to copy."""
    clear()
    register_config_writer(AgentProvider.CLAUDE, ClaudeConfigWriter())
    register_config_writer(AgentProvider.CODEX, CodexConfigWriter())
    yield
    clear()


class TestGetCurrentBuildDir:
    def test_returns_none_when_no_symlink(self, tmp_path):
        with patch("agento.framework.artifacts_dir.BUILD_DIR", str(tmp_path)):
            assert get_current_build_dir("ws", "av") is None

    def test_returns_path_when_symlink_exists(self, tmp_path):
        build_dir = tmp_path / "ws" / "av" / "builds" / "1"
        build_dir.mkdir(parents=True)
        (tmp_path / "ws" / "av" / "current").symlink_to(build_dir)

        with patch("agento.framework.artifacts_dir.BUILD_DIR", str(tmp_path)):
            result = get_current_build_dir("ws", "av")
            assert result is not None
            assert result.is_dir()

    def test_returns_none_when_symlink_target_missing(self, tmp_path):
        link_parent = tmp_path / "ws" / "av"
        link_parent.mkdir(parents=True)
        (link_parent / "current").symlink_to(link_parent / "builds" / "999")

        with patch("agento.framework.artifacts_dir.BUILD_DIR", str(tmp_path)):
            assert get_current_build_dir("ws", "av") is None


class TestCopyBuildToArtifactsDir:
    def test_copies_files(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "CLAUDE.md").write_text("# Test")
        (build_dir / "AGENTS.md").write_text("# Agents")

        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        copy_build_to_artifacts_dir(build_dir, artifacts_dir)

        assert (artifacts_dir / "CLAUDE.md").read_text() == "# Test"
        assert (artifacts_dir / "AGENTS.md").read_text() == "# Agents"

    def test_copies_directories(self, tmp_path, with_writers):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        subdir = build_dir / ".claude" / "skills"
        subdir.mkdir(parents=True)
        (subdir / "test.md").write_text("# Skill")

        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        copy_build_to_artifacts_dir(build_dir, artifacts_dir)

        assert (artifacts_dir / ".claude" / "skills" / "test.md").read_text() == "# Skill"

    def test_handles_empty_build_dir(self, tmp_path):
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        copy_build_to_artifacts_dir(build_dir, artifacts_dir)
        assert list(artifacts_dir.iterdir()) == []

    def test_symlinks_large_directories(self, tmp_path):
        """Large dirs (modules/, KnowledgeBase/) are symlinked, not copied."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "modules" / "jira").mkdir(parents=True)
        (build_dir / "modules" / "jira" / "data.md").write_text("# Jira data")
        (build_dir / "KnowledgeBase").mkdir()
        (build_dir / "KnowledgeBase" / "info.md").write_text("# Info")

        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        copy_build_to_artifacts_dir(build_dir, artifacts_dir)

        # Symlinked, not copied
        assert (artifacts_dir / "modules").is_symlink()
        assert (artifacts_dir / "KnowledgeBase").is_symlink()
        # But content is readable
        assert (artifacts_dir / "modules" / "jira" / "data.md").read_text() == "# Jira data"
        assert (artifacts_dir / "KnowledgeBase" / "info.md").read_text() == "# Info"

    def test_config_files_are_real_copies(self, tmp_path, with_writers):
        """Config files (.claude.json etc) are real copies, not symlinks."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / ".claude.json").write_text('{"model": "test"}')
        (build_dir / "AGENTS.md").write_text("# Agents")

        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        copy_build_to_artifacts_dir(build_dir, artifacts_dir)

        assert not (artifacts_dir / ".claude.json").is_symlink()
        assert not (artifacts_dir / "AGENTS.md").is_symlink()
        assert (artifacts_dir / ".claude.json").read_text() == '{"model": "test"}'

    def test_injects_runtime_params_into_mcp_json(self, tmp_path):
        """job_id is injected into .mcp.json toolbox URLs via ConfigWriter."""
        from agento.modules.claude.src.config import ClaudeConfigWriter

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/sse?agent_view_id=1"}}}
        (build_dir / ".mcp.json").write_text(json.dumps(mcp))

        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        writer = ClaudeConfigWriter()
        with patch("agento.framework.config_writer.get_config_writer", return_value=writer):
            copy_build_to_artifacts_dir(
                build_dir, artifacts_dir,
                job_id=42,
                provider="claude",
            )

        result = json.loads((artifacts_dir / ".mcp.json").read_text())
        url = result["mcpServers"]["toolbox"]["url"]
        assert "job_id=42" in url
        assert "ws=" not in url
        assert "av=" not in url

    def test_no_injection_without_job_id(self, tmp_path):
        """Without job_id, .mcp.json is copied as-is."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/sse?agent_view_id=1"}}}
        (build_dir / ".mcp.json").write_text(json.dumps(mcp))

        artifacts_dir = tmp_path / "run"
        artifacts_dir.mkdir()

        copy_build_to_artifacts_dir(build_dir, artifacts_dir)

        result = json.loads((artifacts_dir / ".mcp.json").read_text())
        assert "job_id" not in result["mcpServers"]["toolbox"]["url"]
