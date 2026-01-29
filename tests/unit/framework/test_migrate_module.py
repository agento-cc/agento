"""Tests for module-aware migration support (Phase 7)."""
from __future__ import annotations

from unittest.mock import MagicMock

from agento.framework.migrate import (
    apply_migration,
    get_all_versions,
    get_applied,
    migrate,
)


def _mock_conn(fetchall_return=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall_return or []
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestGetAppliedModule:
    def test_filters_by_module(self):
        conn, cursor = _mock_conn(fetchall_return=[
            {"version": "001_add_fields"},
        ])

        result = get_applied(conn, module="jira")

        sql = cursor.execute.call_args[0][0]
        assert "WHERE module" in sql
        assert cursor.execute.call_args[0][1] == ("jira",)
        assert result == {"001_add_fields"}

    def test_default_module_is_framework(self):
        conn, cursor = _mock_conn()

        get_applied(conn)

        assert cursor.execute.call_args[0][1] == ("framework",)


class TestGetAllVersionsCustomDir:
    def test_scans_custom_sql_dir(self, tmp_path):
        (tmp_path / "001_first.sql").write_text("SELECT 1;")
        (tmp_path / "002_second.sql").write_text("SELECT 2;")

        versions = get_all_versions(sql_dir=tmp_path)

        assert [v for v, _ in versions] == ["001_first", "002_second"]

    def test_returns_empty_for_missing_dir(self, tmp_path):
        versions = get_all_versions(sql_dir=tmp_path / "nonexistent")

        assert versions == []

    def test_default_scans_framework_dir(self):
        versions = get_all_versions()

        assert len(versions) >= 10
        assert any(v == "001_create_tables" for v, _ in versions)


class TestApplyMigrationModule:
    def test_records_module_in_schema_migrations(self, tmp_path):
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("CREATE TABLE custom (id INT);")
        conn, cursor = _mock_conn()

        apply_migration(conn, "001_test", sql_file, module="jira")

        insert_call = cursor.execute.call_args_list[-1]
        assert "schema_migration" in insert_call[0][0]
        assert insert_call[0][1] == ("001_test", "jira")


class TestMigrateModule:
    def test_applies_module_migrations(self, tmp_path):
        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        (sql_dir / "001_add_fields.sql").write_text("ALTER TABLE jobs ADD COLUMN extra TEXT;")
        conn, _cursor = _mock_conn()

        applied = migrate(conn, module="jira", sql_dir=sql_dir)

        assert applied == ["001_add_fields"]

    def test_module_migrations_empty_dir(self, tmp_path):
        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        conn, _cursor = _mock_conn()

        applied = migrate(conn, module="jira", sql_dir=sql_dir)

        assert applied == []
