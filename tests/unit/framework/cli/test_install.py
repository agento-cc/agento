"""Tests for agento install command."""
from __future__ import annotations

import argparse
import json
import re
import socket
from pathlib import Path
from unittest.mock import patch

from agento.framework.cli.install import (
    InstallCommand,
    _detect_timezone,
    _generate_password,
    _is_port_free,
    _reinstall,
    _sanitize_compose_name,
    _scaffold,
)


class TestSanitizeComposeName:
    def test_lowercase(self):
        assert _sanitize_compose_name("MyProject") == "myproject"

    def test_replaces_spaces(self):
        assert _sanitize_compose_name("My Project") == "my-project"

    def test_replaces_dots(self):
        assert _sanitize_compose_name("project.v2") == "project-v2"

    def test_replaces_underscores(self):
        assert _sanitize_compose_name("my_project") == "my-project"

    def test_strips_invalid_chars(self):
        assert _sanitize_compose_name("proj@#$ect") == "project"

    def test_collapses_hyphens(self):
        assert _sanitize_compose_name("a--b---c") == "a-b-c"

    def test_trims_leading_trailing_hyphens(self):
        assert _sanitize_compose_name("-project-") == "project"

    def test_fallback_to_agento(self):
        assert _sanitize_compose_name("___") == "agento"

    def test_empty_string(self):
        assert _sanitize_compose_name("") == "agento"

    def test_complex_example(self):
        assert _sanitize_compose_name("My Project.v2") == "my-project-v2"


class TestGeneratePassword:
    def test_returns_string(self):
        pw = _generate_password()
        assert isinstance(pw, str)
        assert len(pw) > 16

    def test_unique_per_call(self):
        assert _generate_password() != _generate_password()

    def test_url_safe_chars(self):
        pw = _generate_password()
        assert re.match(r"^[A-Za-z0-9_-]+$", pw), f"Password contains invalid chars: {pw}"


class TestIsPortFree:
    def test_free_port(self):
        assert _is_port_free(0) is True

    def test_occupied_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            assert _is_port_free(port) is False


class TestDetectTimezone:
    def test_returns_string(self):
        tz = _detect_timezone()
        assert isinstance(tz, str)
        assert len(tz) > 0

    def test_fallback_to_utc(self):
        with patch("agento.framework.cli.install.Path") as mock_path:
            mock_path.return_value.resolve.side_effect = OSError("not found")
            tz = _detect_timezone()
            assert tz == "UTC"


class TestScaffold:
    def test_creates_directory_structure(self, tmp_path: Path):
        config = {
            "compose_project_name": "test-proj",
            "agento_version": "0.2.4",
            "mysql_root_password": "rootpass123",
            "mysql_password": "userpass456",
            "mysql_port": "3307",
            "timezone": "Europe/Warsaw",
        }
        _scaffold(tmp_path, "test-proj", config)

        assert (tmp_path / ".agento" / "project.json").is_file()
        assert (tmp_path / "app" / "code").is_dir()
        assert (tmp_path / "workspace" / "systems").is_dir()
        assert (tmp_path / "workspace" / "artifacts").is_dir()
        assert (tmp_path / "workspace" / "build").is_dir()
        assert (tmp_path / "workspace" / "theme").is_dir()
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "tokens").is_dir()
        assert (tmp_path / "storage").is_dir()
        assert (tmp_path / "docker").is_dir()
        assert (tmp_path / ".gitignore").is_file()
        assert (tmp_path / "secrets.env.example").is_file()

    def test_project_json_contents(self, tmp_path: Path):
        config = {
            "compose_project_name": "my-proj",
            "agento_version": "0.2.4",
            "mysql_root_password": "rp",
            "mysql_password": "up",
            "mysql_port": "3306",
            "timezone": "UTC",
        }
        _scaffold(tmp_path, "my-proj", config)

        meta = json.loads((tmp_path / ".agento" / "project.json").read_text())
        assert meta["name"] == "my-proj"
        assert meta["version"] == "0.1.0"
        assert "created_at" in meta

    def test_env_file_rendered(self, tmp_path: Path):
        config = {
            "compose_project_name": "myapp",
            "agento_version": "0.2.4",
            "mysql_root_password": "secret_root",
            "mysql_password": "secret_user",
            "mysql_port": "3307",
            "timezone": "America/New_York",
        }
        _scaffold(tmp_path, "myapp", config)

        env_content = (tmp_path / "docker" / ".env").read_text()
        assert "COMPOSE_PROJECT_NAME=myapp" in env_content
        assert "AGENTO_VERSION=0.2.4" in env_content
        assert "MYSQL_ROOT_PASSWORD=secret_root" in env_content
        assert "MYSQL_PASSWORD=secret_user" in env_content
        assert "MYSQL_PORT=3307" in env_content
        assert "TZ=America/New_York" in env_content
        assert "DISABLE_LLM=0" in env_content
        assert "{" not in env_content

    def test_docker_compose_uses_ghcr_images(self, tmp_path: Path):
        config = {
            "compose_project_name": "x",
            "agento_version": "0.2.4",
            "mysql_root_password": "x",
            "mysql_password": "x",
            "mysql_port": "3306",
            "timezone": "UTC",
        }
        _scaffold(tmp_path, "x", config)

        # Managed base file has GHCR images and DO NOT EDIT header
        compose = (tmp_path / "docker" / "docker-compose.yml").read_text()
        assert "container_name" not in compose
        assert "build:" not in compose
        assert "ghcr.io/agento-cc/agento-toolbox:" in compose
        assert "ghcr.io/agento-cc/agento-cron:" in compose
        assert "${AGENTO_VERSION" in compose
        assert "DO NOT EDIT" in compose

        # User-owned override file is scaffolded
        override = (tmp_path / "docker" / "docker-compose.override.yml").read_text()
        assert "safe to edit" in override

    def test_sql_files_extracted(self, tmp_path: Path):
        config = {
            "compose_project_name": "x",
            "agento_version": "0.2.4",
            "mysql_root_password": "x",
            "mysql_password": "x",
            "mysql_port": "3306",
            "timezone": "UTC",
        }
        _scaffold(tmp_path, "x", config)

        sql_dir = tmp_path / "docker" / "sql"
        assert sql_dir.is_dir()
        sql_files = list(sql_dir.glob("*.sql"))
        assert len(sql_files) > 0


class TestInstallCommandAlreadyInstalled:
    @patch("agento.framework.cli.install.select", return_value=1)  # "No"
    def test_reinstall_declined_exits(self, mock_select, tmp_path: Path, capsys):
        (tmp_path / ".agento").mkdir()
        (tmp_path / ".agento" / "project.json").write_text('{"name":"x"}')

        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            with patch("builtins.input", return_value="."):
                cmd = InstallCommand()
                cmd.execute(argparse.Namespace())
        finally:
            Path.cwd = original_cwd

        captured = capsys.readouterr()
        assert "already installed" in captured.out.lower()


class TestInstallCommandBasic:
    @patch("agento.framework.cli.install._run_post_install")
    @patch("agento.framework.cli.install.select", return_value=0)
    @patch("builtins.input", return_value=".")
    def test_basic_install_scaffolds(self, mock_input, mock_select, mock_post, tmp_path: Path):
        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            cmd = InstallCommand()
            cmd.execute(argparse.Namespace())
        finally:
            Path.cwd = original_cwd

        assert (tmp_path / ".agento" / "project.json").is_file()
        assert (tmp_path / "docker" / ".env").is_file()

        env = (tmp_path / "docker" / ".env").read_text()
        assert "COMPOSE_PROJECT_NAME=" in env
        assert "MYSQL_ROOT_PASSWORD=" in env
        assert "cronagent_pass" not in env
        assert "cronagent_root" not in env


class TestInstallCommandAdvanced:
    @patch("agento.framework.cli.install._run_post_install")
    @patch("agento.framework.cli.install._is_port_free", return_value=True)
    @patch("agento.framework.cli.install.select", return_value=1)
    @patch("builtins.input", side_effect=[".", "custom-name", "3307", "America/Chicago"])
    def test_advanced_install_uses_custom_values(self, mock_input, mock_select, mock_port, mock_post, tmp_path: Path):
        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            cmd = InstallCommand()
            cmd.execute(argparse.Namespace())
        finally:
            Path.cwd = original_cwd

        env = (tmp_path / "docker" / ".env").read_text()
        assert "COMPOSE_PROJECT_NAME=custom-name" in env
        assert "MYSQL_PORT=3307" in env
        assert "TZ=America/Chicago" in env


class TestReinstall:
    def _scaffold_project(self, tmp_path: Path) -> None:
        """Helper: scaffold a project so _reinstall can operate on it."""
        config = {
            "compose_project_name": "myapp",
            "agento_version": "0.1.0",
            "mysql_root_password": "secret_root",
            "mysql_password": "secret_user",
            "mysql_port": "3307",
            "timezone": "Europe/Warsaw",
        }
        _scaffold(tmp_path, "myapp", config)

    @patch("agento.framework.cli.install.get_package_version", return_value="0.5.0")
    def test_reinstall_updates_version_in_env(self, mock_ver, tmp_path: Path):
        self._scaffold_project(tmp_path)
        _reinstall(tmp_path)
        env = (tmp_path / "docker" / ".env").read_text()
        assert "AGENTO_VERSION=0.5.0" in env

    @patch("agento.framework.cli.install.get_package_version", return_value="0.5.0")
    def test_reinstall_preserves_passwords(self, mock_ver, tmp_path: Path):
        self._scaffold_project(tmp_path)
        _reinstall(tmp_path)
        env = (tmp_path / "docker" / ".env").read_text()
        assert "MYSQL_ROOT_PASSWORD=secret_root" in env
        assert "MYSQL_PASSWORD=secret_user" in env
        assert "MYSQL_PORT=3307" in env

    @patch("agento.framework.cli.install.get_package_version", return_value="0.5.0")
    def test_reinstall_refreshes_compose_but_not_override(self, mock_ver, tmp_path: Path):
        self._scaffold_project(tmp_path)
        # Corrupt managed file to verify it gets refreshed
        (tmp_path / "docker" / "docker-compose.yml").write_text("corrupted")
        # Add custom content to override
        (tmp_path / "docker" / "docker-compose.override.yml").write_text("services:\n  redis:\n    image: redis:7\n")
        _reinstall(tmp_path)
        # Managed file refreshed
        compose = (tmp_path / "docker" / "docker-compose.yml").read_text()
        assert "ghcr.io/agento-cc/agento-cron" in compose
        # Override untouched
        override = (tmp_path / "docker" / "docker-compose.override.yml").read_text()
        assert "redis:7" in override

    @patch("agento.framework.cli.install.get_package_version", return_value="0.5.0")
    def test_reinstall_updates_project_json_version(self, mock_ver, tmp_path: Path):
        self._scaffold_project(tmp_path)
        _reinstall(tmp_path)
        meta = json.loads((tmp_path / ".agento" / "project.json").read_text())
        assert meta["version"] == "0.5.0"
