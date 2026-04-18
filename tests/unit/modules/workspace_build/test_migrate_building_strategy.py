"""Tests for the MigrateBuildingStrategy data patch."""
from __future__ import annotations

from agento.modules.workspace_build.src.patches.migrate_building_strategy import (
    MigrateBuildingStrategy,
)


class _FakeConn:
    """Minimal DB double that mimics the PyMySQL dict cursor behaviour used by patches."""

    def __init__(self, rows: list[dict]):
        self._rows: list[dict] = list(rows)
        self.committed: int = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1


class _FakeCursor:
    def __init__(self, conn: _FakeConn):
        self._conn = conn
        self._result: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params: tuple):
        sql_stripped = " ".join(sql.split()).lower()
        if sql_stripped.startswith("select scope, scope_id, value, encrypted from core_config_data where path"):
            (path,) = params
            self._result = [r for r in self._conn._rows if r["path"] == path]
        elif sql_stripped.startswith("select 1 from core_config_data where scope"):
            scope, scope_id, path = params
            match = [
                r for r in self._conn._rows
                if r["scope"] == scope and r["scope_id"] == scope_id and r["path"] == path
            ]
            self._result = [{"1": 1}] if match else []
        elif sql_stripped.startswith("insert into core_config_data"):
            scope, scope_id, path, value, encrypted = params
            self._conn._rows.append({
                "scope": scope,
                "scope_id": scope_id,
                "path": path,
                "value": value,
                "encrypted": encrypted,
            })
        elif sql_stripped.startswith("delete from core_config_data"):
            scope, scope_id, path = params
            self._conn._rows = [
                r for r in self._conn._rows
                if not (r["scope"] == scope and r["scope_id"] == scope_id and r["path"] == path)
            ]
        else:
            raise AssertionError(f"Unexpected SQL in patch: {sql!r}")

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class TestMigrateBuildingStrategy:
    def test_noop_when_old_key_absent(self):
        conn = _FakeConn([])
        MigrateBuildingStrategy().apply(conn)
        assert conn._rows == []
        # No work → commit still runs? Implementation returns before commit when rows empty.
        assert conn.committed == 0

    def test_moves_global_value_to_new_key(self):
        conn = _FakeConn([
            {"scope": "default", "scope_id": 0,
             "path": "workspace_build/building_strategy", "value": "symlink", "encrypted": 0},
        ])
        MigrateBuildingStrategy().apply(conn)

        paths = [(r["scope"], r["scope_id"], r["path"], r["value"]) for r in conn._rows]
        assert ("default", 0, "workspace_build/strategy/modules", "symlink") in paths
        assert all(p[2] != "workspace_build/building_strategy" for p in paths)

    def test_preserves_scope_of_old_value(self):
        conn = _FakeConn([
            {"scope": "workspace", "scope_id": 7,
             "path": "workspace_build/building_strategy", "value": "symlink", "encrypted": 0},
            {"scope": "agent_view", "scope_id": 42,
             "path": "workspace_build/building_strategy", "value": "copy", "encrypted": 0},
        ])
        MigrateBuildingStrategy().apply(conn)

        by_path = {(r["scope"], r["scope_id"], r["path"]): r["value"] for r in conn._rows}
        assert by_path.get(("workspace", 7, "workspace_build/strategy/modules")) == "symlink"
        assert by_path.get(("agent_view", 42, "workspace_build/strategy/modules")) == "copy"
        # Old rows gone
        assert not any(r["path"] == "workspace_build/building_strategy" for r in conn._rows)

    def test_destination_exists_keeps_existing_value(self):
        """If operator already set the new key, don't overwrite it; still drop the old row."""
        conn = _FakeConn([
            {"scope": "default", "scope_id": 0,
             "path": "workspace_build/building_strategy", "value": "symlink", "encrypted": 0},
            {"scope": "default", "scope_id": 0,
             "path": "workspace_build/strategy/modules", "value": "copy", "encrypted": 0},
        ])
        MigrateBuildingStrategy().apply(conn)

        values = {r["path"]: r["value"] for r in conn._rows}
        assert values.get("workspace_build/strategy/modules") == "copy"
        assert "workspace_build/building_strategy" not in values

    def test_idempotent(self):
        conn = _FakeConn([
            {"scope": "default", "scope_id": 0,
             "path": "workspace_build/building_strategy", "value": "symlink", "encrypted": 0},
        ])
        patch = MigrateBuildingStrategy()
        patch.apply(conn)
        snapshot = list(conn._rows)
        patch.apply(conn)
        assert conn._rows == snapshot

    def test_require_is_empty(self):
        assert MigrateBuildingStrategy().require() == []
