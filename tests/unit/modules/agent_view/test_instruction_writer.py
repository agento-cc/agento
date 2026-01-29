"""Tests for per-run instruction file writer."""
from agento.modules.agent_view.src.instruction_writer import (
    CLAUDE_MD_CONTENT,
    write_instruction_files,
)


class TestWriteFromConfig:
    def test_writes_agents_md_from_config(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        overrides = {"agent/instructions/agents_md": ("# Custom AGENTS", False)}

        write_instruction_files(run_dir, overrides)

        assert (run_dir / "AGENTS.md").read_text() == "# Custom AGENTS"

    def test_writes_soul_md_from_config(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        overrides = {"agent/instructions/soul_md": ("# Custom SOUL", False)}

        write_instruction_files(run_dir, overrides)

        assert (run_dir / "SOUL.md").read_text() == "# Custom SOUL"

    def test_db_value_overrides_workspace_file(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "AGENTS.md").write_text("workspace default")
        overrides = {"agent/instructions/agents_md": ("db override", False)}

        write_instruction_files(run_dir, overrides, workspace_dir=ws_dir)

        assert (run_dir / "AGENTS.md").read_text() == "db override"


class TestFallbackToWorkspace:
    def test_copies_from_workspace_when_no_config(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "AGENTS.md").write_text("workspace agents")
        (ws_dir / "SOUL.md").write_text("workspace soul")

        write_instruction_files(run_dir, {}, workspace_dir=ws_dir)

        assert (run_dir / "AGENTS.md").read_text() == "workspace agents"
        assert (run_dir / "SOUL.md").read_text() == "workspace soul"

    def test_no_workspace_file_no_config_skips(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        ws_dir = tmp_path / "empty_workspace"
        ws_dir.mkdir()

        write_instruction_files(run_dir, {}, workspace_dir=ws_dir)

        assert not (run_dir / "AGENTS.md").exists()
        assert not (run_dir / "SOUL.md").exists()


class TestClaudeMd:
    def test_always_writes_claude_md(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        write_instruction_files(run_dir, {})

        assert (run_dir / "CLAUDE.md").read_text() == CLAUDE_MD_CONTENT

    def test_claude_md_written_even_without_agents(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        ws_dir = tmp_path / "empty"
        ws_dir.mkdir()

        write_instruction_files(run_dir, {}, workspace_dir=ws_dir)

        assert (run_dir / "CLAUDE.md").exists()
        assert not (run_dir / "AGENTS.md").exists()


class TestEmptyConfigValue:
    def test_empty_string_falls_back_to_workspace(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "AGENTS.md").write_text("workspace default")
        overrides = {"agent/instructions/agents_md": ("", False)}

        write_instruction_files(run_dir, overrides, workspace_dir=ws_dir)

        assert (run_dir / "AGENTS.md").read_text() == "workspace default"
