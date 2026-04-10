"""Tests for agento upgrade command."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agento.framework.cli._project import update_dotenv_value


class TestUpgradeUpdatesEnv:
    def test_updates_version(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("AGENTO_VERSION=0.2.0\nMYSQL_PASSWORD=secret\n")
        update_dotenv_value(env, "AGENTO_VERSION", "0.3.0")
        content = env.read_text()
        assert "AGENTO_VERSION=0.3.0\n" in content
        assert "MYSQL_PASSWORD=secret\n" in content

    def test_specific_version(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("AGENTO_VERSION=0.2.0\n")
        update_dotenv_value(env, "AGENTO_VERSION", "0.4.0")
        assert "AGENTO_VERSION=0.4.0\n" in env.read_text()


class TestUpgradeCommand:
    @patch("agento.framework.cli.upgrade.subprocess.run")
    @patch("agento.framework.cli.upgrade._upgrade_cli", return_value="0.5.0")
    @patch("agento.framework.cli.upgrade._fetch_latest_pypi_version", return_value="0.5.0")
    @patch("agento.framework.cli.upgrade.get_package_version", return_value="0.4.0")
    @patch("agento.framework.cli.upgrade.find_compose_file")
    @patch("agento.framework.cli.upgrade.find_project_root")
    def test_defaults_to_latest_pypi_version(
        self, mock_root, mock_compose, mock_ver, mock_pypi, mock_cli, mock_run, tmp_path: Path
    ):
        from argparse import Namespace

        from agento.framework.cli.upgrade import UpgradeCommand

        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        env = tmp_path / "docker" / ".env"
        env.write_text("AGENTO_VERSION=0.2.0\n")
        mock_compose.return_value = tmp_path / "docker" / "docker-compose.yml"
        mock_run.return_value = type("R", (), {"returncode": 0})()

        cmd = UpgradeCommand()
        cmd.execute(Namespace(version=None))

        assert "AGENTO_VERSION=0.5.0\n" in env.read_text()
        mock_pypi.assert_called_once()
        mock_cli.assert_called_once_with("0.5.0")

    @patch("agento.framework.cli.upgrade.subprocess.run")
    @patch("agento.framework.cli.upgrade._upgrade_cli", return_value="0.9.0")
    @patch("agento.framework.cli.upgrade.get_package_version", return_value="0.4.0")
    @patch("agento.framework.cli.upgrade.find_compose_file")
    @patch("agento.framework.cli.upgrade.find_project_root")
    def test_uses_explicit_version(
        self, mock_root, mock_compose, mock_ver, mock_cli, mock_run, tmp_path: Path
    ):
        from argparse import Namespace

        from agento.framework.cli.upgrade import UpgradeCommand

        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        env = tmp_path / "docker" / ".env"
        env.write_text("AGENTO_VERSION=0.2.0\n")
        mock_compose.return_value = tmp_path / "docker" / "docker-compose.yml"
        mock_run.return_value = type("R", (), {"returncode": 0})()

        cmd = UpgradeCommand()
        cmd.execute(Namespace(version="0.9.0"))

        assert "AGENTO_VERSION=0.9.0\n" in env.read_text()
        mock_cli.assert_called_once_with("0.9.0")

    @patch("agento.framework.cli.upgrade.subprocess.run")
    @patch("agento.framework.cli.upgrade._upgrade_cli", return_value="0.5.0")
    @patch("agento.framework.cli.upgrade.get_package_version", return_value="0.5.0")
    @patch("agento.framework.cli.upgrade.find_compose_file")
    @patch("agento.framework.cli.upgrade.find_project_root")
    def test_skips_cli_upgrade_when_already_at_version(
        self, mock_root, mock_compose, mock_ver, mock_cli, mock_run, tmp_path: Path
    ):
        from argparse import Namespace

        from agento.framework.cli.upgrade import UpgradeCommand

        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        env = tmp_path / "docker" / ".env"
        env.write_text("AGENTO_VERSION=0.2.0\n")
        mock_compose.return_value = tmp_path / "docker" / "docker-compose.yml"
        mock_run.return_value = type("R", (), {"returncode": 0})()

        cmd = UpgradeCommand()
        cmd.execute(Namespace(version="0.5.0"))

        # CLI upgrade not called because current == target
        mock_cli.assert_not_called()
        assert "AGENTO_VERSION=0.5.0\n" in env.read_text()

    @patch("agento.framework.cli.upgrade.subprocess.run")
    @patch("agento.framework.cli.upgrade._upgrade_cli", return_value="0.6.0")
    @patch("agento.framework.cli.upgrade.get_package_version", return_value="0.5.0")
    @patch("agento.framework.cli.upgrade.find_compose_file")
    @patch("agento.framework.cli.upgrade.find_project_root")
    def test_upgrade_refreshes_compose(
        self, mock_root, mock_compose, mock_ver, mock_cli, mock_run, tmp_path: Path
    ):
        from argparse import Namespace

        from agento.framework.cli.upgrade import UpgradeCommand

        mock_root.return_value = tmp_path
        (tmp_path / "docker").mkdir()
        env = tmp_path / "docker" / ".env"
        env.write_text("AGENTO_VERSION=0.5.0\n")
        (tmp_path / "docker" / "docker-compose.yml").write_text("old")
        mock_compose.return_value = tmp_path / "docker" / "docker-compose.yml"
        mock_run.return_value = type("R", (), {"returncode": 0})()

        cmd = UpgradeCommand()
        cmd.execute(Namespace(version="0.6.0"))

        compose = (tmp_path / "docker" / "docker-compose.yml").read_text()
        assert "ghcr.io/agento-cc/agento-cron" in compose
        assert "DO NOT EDIT" in compose
