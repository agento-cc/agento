"""Tests for `agento run <agent_view_code> [prompt]` — RunCommand."""
from __future__ import annotations

import argparse
import json
import subprocess
from unittest.mock import patch

import pytest

from agento.framework.cli.run import RunCommand

_INTERACTIVE_CLAUDE = ["claude"]
_HEADLESS_CLAUDE = [
    "claude", "-p", "jakie masz toole z mcp i skille?",
    "--dangerously-skip-permissions",
    "--output-format", "stream-json",
    "--verbose",
    "--model", "claude-opus-4-6",
]
_INTERACTIVE_CODEX = ["codex"]
_HEADLESS_CODEX = [
    "codex", "exec", "jakie masz toole z mcp i skille?",
    "--dangerously-bypass-approvals-and-sandbox",
    "--skip-git-repo-check",
    "--model", "gpt-5.4",
]


def _base_runtime(provider="claude", model="claude-opus-4-6", *, prompt=False):
    return {
        "agent_view_id": 2,
        "agent_view_code": "dev_01",
        "workspace_id": 1,
        "workspace_code": "it",
        "provider": provider,
        "model": model,
        "home": "/workspace/build/it/dev_01/current",
        "interactive_command": _INTERACTIVE_CLAUDE if provider == "claude" else _INTERACTIVE_CODEX,
        "headless_command": (
            (_HEADLESS_CLAUDE if provider == "claude" else _HEADLESS_CODEX) if prompt else None
        ),
    }


def _make_args(code="dev_01"):
    return argparse.Namespace(agent_view_code=code, prompt=[])


def _make_prompt_args(code="dev_01", prompt="jakie masz toole z mcp i skille?"):
    return argparse.Namespace(agent_view_code=code, prompt=[prompt])


def _project_layout(tmp_path, *, include_current=True):
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    compose = docker_dir / "docker-compose.yml"
    compose.write_text("name: agento\nservices: {}\n")
    (tmp_path / ".agento").mkdir()
    (tmp_path / ".agento" / "project.json").write_text("{}")
    if include_current:
        build_root = tmp_path / "workspace" / "build" / "it" / "dev_01"
        build_root.mkdir(parents=True)
        (build_root / "builds").mkdir()
        (build_root / "current").symlink_to(build_root / "builds")
    return tmp_path, compose


class TestRunCommand:
    def test_properties(self):
        cmd = RunCommand()
        assert cmd.name == "run"
        assert cmd.shortcut == "ru"

    def test_missing_project_root_exits(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=None),
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_args())
        assert exc.value.code == 1
        assert "not inside an agento project" in capsys.readouterr().err

    def test_missing_compose_file_exits(self, tmp_path, capsys):
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=tmp_path),
            patch("agento.framework.cli.run.find_compose_file", return_value=None),
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_args())
        assert exc.value.code == 1
        assert "docker-compose.yml not found" in capsys.readouterr().err

    def test_missing_provider_exits_with_hint(self, tmp_path, capsys):
        project_root, compose = _project_layout(tmp_path)
        runtime = {**_base_runtime(), "provider": None, "interactive_command": None}
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=runtime),
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_args())
        err = capsys.readouterr().err
        assert exc.value.code == 1
        assert "no provider configured" in err
        assert "config:set agent_view/provider" in err

    def test_unregistered_cli_invoker_exits(self, tmp_path, capsys):
        project_root, compose = _project_layout(tmp_path)
        runtime = {**_base_runtime(provider="exotic"), "interactive_command": None}
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=runtime),
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_args())
        err = capsys.readouterr().err
        assert exc.value.code == 1
        assert "no CliInvoker registered" in err

    def test_missing_ssh_key_prints_note(self, tmp_path, capsys):
        project_root, compose = _project_layout(tmp_path)
        # build/current exists but has no .ssh/id_rsa
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=_base_runtime()),
            patch("agento.framework.cli.run.os.execvp"),
        ):
            RunCommand().execute(_make_args())
        err = capsys.readouterr().err
        assert "no .ssh/id_rsa" in err
        assert "config:set agent_view/identity/ssh_private_key" in err

    def test_existing_ssh_key_suppresses_note(self, tmp_path, capsys):
        project_root, compose = _project_layout(tmp_path)
        build_root = project_root / "workspace" / "build" / "it" / "dev_01"
        (build_root / "builds" / ".ssh").mkdir(parents=True)
        (build_root / "builds" / ".ssh" / "id_rsa").write_text("KEY")
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=_base_runtime()),
            patch("agento.framework.cli.run.os.execvp"),
        ):
            RunCommand().execute(_make_args())
        err = capsys.readouterr().err
        assert "no .ssh/id_rsa" not in err

    def test_missing_current_build_exits_with_hint(self, tmp_path, capsys):
        project_root, compose = _project_layout(tmp_path, include_current=False)
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=_base_runtime()),
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_args())
        err = capsys.readouterr().err
        assert exc.value.code == 1
        assert "no build found" in err
        assert "workspace:build --agent-view dev_01" in err

    def test_interactive_happy_path_uses_returned_command(self, tmp_path):
        project_root, compose = _project_layout(tmp_path)
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=_base_runtime()),
            patch("agento.framework.cli.run.os.execvp") as mock_execvp,
        ):
            RunCommand().execute(_make_args())
        mock_execvp.assert_called_once()
        program, argv = mock_execvp.call_args.args
        assert program == "docker"
        assert argv[:4] == ["docker", "compose", "-f", str(compose)]
        assert "exec" in argv
        assert "-it" in argv
        assert "sandbox" in argv
        assert argv[-1] == "claude"
        assert "HOME=/workspace/build/it/dev_01/current" in argv
        assert argv[argv.index("-w") + 1] == "/workspace/build/it/dev_01/current"

    def test_interactive_for_codex_uses_codex_binary(self, tmp_path):
        project_root, compose = _project_layout(tmp_path)
        runtime = _base_runtime(provider="codex", model="gpt-5.4")
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=runtime),
            patch("agento.framework.cli.run.os.execvp") as mock_execvp,
        ):
            RunCommand().execute(_make_args())
        _, argv = mock_execvp.call_args.args
        assert argv[-1] == "codex"

    def test_headless_claude_uses_headless_command_from_runtime(self, tmp_path):
        project_root, compose = _project_layout(tmp_path)
        runtime = _base_runtime(prompt=True)
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=runtime) as mock_fetch,
            patch("agento.framework.cli.run.subprocess.run", return_value=completed) as mock_run,
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_prompt_args())
        assert exc.value.code == 0
        # _fetch_runtime was called with the prompt so cron can build the headless command
        assert mock_fetch.call_args.kwargs["prompt"] == "jakie masz toole z mcp i skille?"

        argv = mock_run.call_args.args[0]
        assert "-T" in argv and "-it" not in argv
        # After "sandbox" comes the ssh-prelude wrapper: sh -c <script> -- <cmd...>
        idx = argv.index("sandbox") + 1
        assert argv[idx:idx + 2] == ["sh", "-c"]
        assert argv[idx + 3] == "--"
        assert argv[idx + 4:] == _HEADLESS_CLAUDE
        assert mock_run.call_args.kwargs["stdin"] == subprocess.DEVNULL

    def test_headless_codex_uses_headless_command_from_runtime(self, tmp_path):
        project_root, compose = _project_layout(tmp_path)
        runtime = _base_runtime(provider="codex", model="gpt-5.4", prompt=True)
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=runtime),
            patch("agento.framework.cli.run.subprocess.run", return_value=completed) as mock_run,
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_prompt_args())
        assert exc.value.code == 0
        argv = mock_run.call_args.args[0]
        idx = argv.index("sandbox") + 1
        assert argv[idx:idx + 2] == ["sh", "-c"]
        assert argv[idx + 4:] == _HEADLESS_CODEX

    def test_headless_propagates_exit_code(self, tmp_path):
        project_root, compose = _project_layout(tmp_path)
        runtime = _base_runtime(provider="codex", model="gpt-5.4", prompt=True)
        completed = subprocess.CompletedProcess(args=[], returncode=17)
        with (
            patch("agento.framework.cli.run.find_project_root", return_value=project_root),
            patch("agento.framework.cli.run.find_compose_file", return_value=compose),
            patch("agento.framework.cli.run._fetch_runtime", return_value=runtime),
            patch("agento.framework.cli.run.subprocess.run", return_value=completed),
            pytest.raises(SystemExit) as exc,
        ):
            RunCommand().execute(_make_prompt_args())
        assert exc.value.code == 17


class TestFetchRuntime:
    def test_parses_cron_json(self, tmp_path):
        from agento.framework.cli.run import _fetch_runtime

        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps(_base_runtime()) + "\n",
            stderr="",
        )
        with patch("agento.framework.cli.run.subprocess.run", return_value=fake_result):
            result = _fetch_runtime(tmp_path / "compose.yml", "dev_01")
        assert result["interactive_command"] == _INTERACTIVE_CLAUDE
        assert result["headless_command"] is None

    def test_passes_prompt_flag_to_container(self, tmp_path):
        from agento.framework.cli.run import _fetch_runtime

        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps(_base_runtime(prompt=True)) + "\n",
            stderr="",
        )
        with patch(
            "agento.framework.cli.run.subprocess.run", return_value=fake_result,
        ) as mock_run:
            _fetch_runtime(tmp_path / "compose.yml", "dev_01", prompt="hello")
        cmd = mock_run.call_args.args[0]
        assert "--prompt" in cmd
        assert cmd[cmd.index("--prompt") + 1] == "hello"

    def test_propagates_nonzero_exit(self, tmp_path, capsys):
        from agento.framework.cli.run import _fetch_runtime

        fake_result = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="", stderr="Error: agent_view 'missing' not found\n",
        )
        with (
            patch("agento.framework.cli.run.subprocess.run", return_value=fake_result),
            pytest.raises(SystemExit) as exc,
        ):
            _fetch_runtime(tmp_path / "compose.yml", "missing")
        assert exc.value.code == 1
        assert "agent_view 'missing' not found" in capsys.readouterr().err

    def test_bad_json_exits(self, tmp_path, capsys):
        from agento.framework.cli.run import _fetch_runtime

        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="not json at all", stderr="",
        )
        with (
            patch("agento.framework.cli.run.subprocess.run", return_value=fake_result),
            pytest.raises(SystemExit) as exc,
        ):
            _fetch_runtime(tmp_path / "compose.yml", "dev_01")
        assert exc.value.code == 1
        assert "could not parse runtime JSON" in capsys.readouterr().err
