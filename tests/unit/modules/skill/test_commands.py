"""Tests for skill CLI commands."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

from agento.modules.skill.src.commands.skill_disable import SkillDisableCommand
from agento.modules.skill.src.commands.skill_enable import SkillEnableCommand
from agento.modules.skill.src.commands.skill_list import SkillListCommand
from agento.modules.skill.src.commands.skill_sync import SkillSyncCommand
from agento.modules.skill.src.registry import SkillInfo


class TestSkillSyncCommand:
    def test_properties(self):
        cmd = SkillSyncCommand()
        assert cmd.name == "skill:sync"
        assert cmd.shortcut == "sk:sy"
        assert cmd.help

    @patch("agento.framework.bootstrap.get_module_config")
    @patch("agento.modules.skill.src.registry.sync_skills")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_execute(self, mock_config, mock_conn, mock_sync, mock_mod_config, capsys):
        mock_config.return_value = ({}, None, None)
        mock_mod_config.return_value = {"skills_dir": "workspace/.claude/skills"}
        conn = MagicMock()
        mock_conn.return_value = conn
        mock_sync.return_value = MagicMock(new=2, updated=1, unchanged=3)

        cmd = SkillSyncCommand()
        cmd.execute(Namespace())

        captured = capsys.readouterr()
        assert "2 new" in captured.out
        assert "1 updated" in captured.out
        assert "3 unchanged" in captured.out
        conn.close.assert_called_once()


class TestSkillListCommand:
    def test_properties(self):
        cmd = SkillListCommand()
        assert cmd.name == "skill:list"
        assert cmd.shortcut == "sk:li"
        assert cmd.help

    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.modules.skill.src.registry.get_all_skills")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_execute_no_skills(self, mock_config, mock_conn, mock_get_all, mock_overrides, capsys):
        mock_config.return_value = ({}, None, None)
        mock_conn.return_value = MagicMock()
        mock_get_all.return_value = []

        cmd = SkillListCommand()
        cmd.execute(Namespace(agent_view_code=None))

        captured = capsys.readouterr()
        assert "No skills registered" in captured.out

    @patch("agento.framework.scoped_config.build_scoped_overrides")
    @patch("agento.modules.skill.src.registry.get_all_skills")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_execute_with_skills(self, mock_config, mock_conn, mock_get_all, mock_overrides, capsys):
        mock_config.return_value = ({}, None, None)
        conn = MagicMock()
        mock_conn.return_value = conn
        mock_get_all.return_value = [
            SkillInfo(name="alpha", path="/a", description="Alpha skill", checksum="aaa"),
            SkillInfo(name="beta", path="/b", description="Beta skill", checksum="bbb"),
        ]
        mock_overrides.return_value = {"skill/beta/is_enabled": ("0", False)}

        cmd = SkillListCommand()
        cmd.execute(Namespace(agent_view_code=None))

        captured = capsys.readouterr()
        assert "alpha" in captured.out
        assert "enabled" in captured.out
        assert "beta" in captured.out
        assert "disabled" in captured.out
        conn.close.assert_called_once()


class TestSkillEnableCommand:
    def test_properties(self):
        cmd = SkillEnableCommand()
        assert cmd.name == "skill:enable"
        assert cmd.shortcut == "sk:en"
        assert cmd.help

    @patch("agento.framework.scoped_config.scoped_config_set")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_execute(self, mock_config, mock_conn, mock_set, capsys):
        mock_config.return_value = ({}, None, None)
        conn = MagicMock()
        mock_conn.return_value = conn

        cmd = SkillEnableCommand()
        cmd.execute(Namespace(skill_name="my_skill", scope="default", scope_id=0, agent_view_code=None))

        mock_set.assert_called_once_with(conn, "skill/my_skill/is_enabled", "1", scope="default", scope_id=0)
        conn.commit.assert_called_once()
        conn.close.assert_called_once()
        captured = capsys.readouterr()
        assert "Enabled" in captured.out


class TestSkillDisableCommand:
    def test_properties(self):
        cmd = SkillDisableCommand()
        assert cmd.name == "skill:disable"
        assert cmd.shortcut == "sk:di"
        assert cmd.help

    @patch("agento.framework.scoped_config.scoped_config_set")
    @patch("agento.framework.db.get_connection")
    @patch("agento.framework.cli.runtime._load_framework_config")
    def test_execute(self, mock_config, mock_conn, mock_set, capsys):
        mock_config.return_value = ({}, None, None)
        conn = MagicMock()
        mock_conn.return_value = conn

        cmd = SkillDisableCommand()
        cmd.execute(Namespace(skill_name="my_skill", scope="agent_view", scope_id=5, agent_view_code=None))

        mock_set.assert_called_once_with(conn, "skill/my_skill/is_enabled", "0", scope="agent_view", scope_id=5)
        conn.commit.assert_called_once()
        conn.close.assert_called_once()
        captured = capsys.readouterr()
        assert "Disabled" in captured.out
