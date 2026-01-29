"""Tests for DatabaseConfig framework dataclass."""
import pytest

from agento.framework.database_config import DatabaseConfig


class TestDatabaseConfigDefaults:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert cfg.mysql_host == ""
        assert cfg.mysql_port == 3306
        assert cfg.mysql_database == ""
        assert cfg.mysql_user == ""
        assert cfg.mysql_password == ""

    def test_frozen(self):
        cfg = DatabaseConfig()
        with pytest.raises(AttributeError):
            cfg.mysql_host = "newhost"


class TestDatabaseConfigFromEnv:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MYSQL_HOST", "db.local")
        monkeypatch.setenv("MYSQL_PORT", "3307")
        monkeypatch.setenv("MYSQL_DATABASE", "mydb")
        monkeypatch.setenv("MYSQL_USER", "admin")
        monkeypatch.setenv("MYSQL_PASSWORD", "secret")

        cfg = DatabaseConfig.from_env()
        assert cfg.mysql_host == "db.local"
        assert cfg.mysql_port == 3307
        assert cfg.mysql_database == "mydb"
        assert cfg.mysql_user == "admin"
        assert cfg.mysql_password == "secret"

    def test_defaults(self):
        cfg = DatabaseConfig.from_env()
        assert cfg.mysql_host == "mysql"
        assert cfg.mysql_port == 3306
        assert cfg.mysql_database == "cron_agent"
        assert cfg.mysql_user == "cron_agent"
        assert cfg.mysql_password == ""

    def test_backward_compat_alias(self):
        cfg = DatabaseConfig.from_env_and_json({"mysql": {"host": "ignored"}})
        assert cfg.mysql_host == "mysql"  # json data is ignored
