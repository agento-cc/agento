"""Tests for skill module observers."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from agento.modules.skill.src.observers import SkillSyncOnSetupObserver


@dataclass
class FakeSetupCompleteEvent:
    dry_run: bool = False


class TestSkillSyncOnSetupObserver:
    @patch("agento.modules.skill.src.registry.sync_skills_multi")
    def test_skips_on_dry_run(self, mock_sync):
        observer = SkillSyncOnSetupObserver()
        event = FakeSetupCompleteEvent(dry_run=True)

        observer.execute(event)
        mock_sync.assert_not_called()

    @patch("agento.framework.bootstrap.get_manifests", return_value=[])
    @patch("agento.framework.bootstrap.get_module_config")
    @patch("agento.modules.skill.src.registry.sync_skills_multi")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.database_config.DatabaseConfig.from_env")
    def test_syncs_skills_on_setup_complete(
        self, mock_db_config, mock_conn, mock_sync, mock_mod_config, _mock_manifests, capsys
    ):
        mock_mod_config.return_value = {"skills_dir": "workspace/.claude/skills"}
        conn = MagicMock()
        mock_conn.return_value = conn
        mock_sync.return_value = MagicMock(new=2, updated=1, unchanged=3)

        observer = SkillSyncOnSetupObserver()
        observer.execute(FakeSetupCompleteEvent(dry_run=False))

        mock_sync.assert_called_once()
        conn.close.assert_called_once()

        captured = capsys.readouterr()
        assert "2 new" in captured.out
        assert "1 updated" in captured.out
        assert "3 unchanged" in captured.out

    @patch("agento.framework.bootstrap.get_manifests")
    @patch("agento.framework.bootstrap.get_module_config")
    @patch("agento.modules.skill.src.registry.sync_skills_multi")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.database_config.DatabaseConfig.from_env")
    def test_includes_module_skills_dirs(
        self, mock_db_config, mock_conn, mock_sync, mock_mod_config, mock_manifests, tmp_path
    ):
        # Create a fake module with a skills/ subdirectory
        mod_path = tmp_path / "mymodule"
        (mod_path / "skills").mkdir(parents=True)

        manifest = MagicMock()
        manifest.path = str(mod_path)
        mock_manifests.return_value = [manifest]

        mock_mod_config.return_value = {"skills_dir": "workspace/.claude/skills"}
        conn = MagicMock()
        mock_conn.return_value = conn
        mock_sync.return_value = MagicMock(new=0, updated=0, unchanged=0)

        observer = SkillSyncOnSetupObserver()
        observer.execute(FakeSetupCompleteEvent(dry_run=False))

        call_args = mock_sync.call_args
        skills_dirs = call_args[0][1]
        assert len(skills_dirs) == 2
        assert skills_dirs[1] == mod_path / "skills"

    @patch("agento.framework.database_config.DatabaseConfig.from_env", side_effect=Exception("db error"))
    @patch("agento.framework.bootstrap.get_manifests", return_value=[])
    @patch("agento.framework.bootstrap.get_module_config", return_value={})
    def test_handles_db_error_gracefully(self, _mock_config, _mock_manifests, _mock_db_config):
        observer = SkillSyncOnSetupObserver()
        # Should not raise
        observer.execute(FakeSetupCompleteEvent(dry_run=False))

    @patch("agento.framework.bootstrap.get_manifests", return_value=[])
    @patch("agento.framework.bootstrap.get_module_config", return_value={})
    @patch("agento.modules.skill.src.registry.sync_skills_multi", side_effect=Exception("sync failed"))
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.database_config.DatabaseConfig.from_env")
    def test_connection_closed_on_error(
        self, mock_db_config, mock_conn, mock_sync, _mock_config, _mock_manifests
    ):
        conn = MagicMock()
        mock_conn.return_value = conn

        observer = SkillSyncOnSetupObserver()
        # Should not raise despite sync_skills_multi failing
        observer.execute(FakeSetupCompleteEvent(dry_run=False))

        conn.close.assert_called_once()
