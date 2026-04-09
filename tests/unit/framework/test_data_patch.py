"""Tests for data patch protocol and executor (Phase 7)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agento.framework.data_patch import (
    CyclicPatchDependencyError,
    apply_patch,
    get_all_applied,
    get_all_pending,
    get_applied_patches,
    resolve_patch_order,
)
from agento.framework.event_manager import ObserverEntry, get_event_manager
from agento.framework.event_manager import clear as clear_event_manager
from agento.framework.events import DataPatchAppliedEvent
from agento.framework.module_loader import ModuleManifest


def _mock_conn(fetchall_return=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall_return or []
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def _make_manifest(tmp_path: Path, name: str, patches: list[dict]) -> ModuleManifest:
    """Create a manifest with patch classes on disk."""
    mod_dir = tmp_path / name
    mod_dir.mkdir(exist_ok=True)
    patches_dir = mod_dir / "src" / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)

    for p in patches:
        # e.g. class_path="src.patches.populate.PopulateDefaults"
        parts = p["class"].rsplit(".", 2)
        file_name = parts[-2] + ".py"
        class_name = parts[-1]
        require_list = p.get("_require", [])
        (patches_dir / file_name).write_text(
            f"class {class_name}:\n"
            f"    def apply(self, conn): pass\n"
            f"    def require(self): return {require_list!r}\n"
        )

    return ModuleManifest(
        name=name,
        version="1.0.0",
        description=f"Test module {name}",
        path=mod_dir,
        data_patches={"patches": [{k: v for k, v in p.items() if not k.startswith("_")} for p in patches]},
    )


class TestGetAppliedPatches:
    def test_returns_applied_set(self):
        conn, _ = _mock_conn(fetchall_return=[
            {"name": "PopulateDefaults"},
            {"name": "SeedData"},
        ])

        result = get_applied_patches(conn, "jira")

        assert result == {"PopulateDefaults", "SeedData"}

    def test_empty_when_none_applied(self):
        conn, _ = _mock_conn()

        result = get_applied_patches(conn, "jira")

        assert result == set()

    def test_handles_missing_table(self):
        import pymysql.err

        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = pymysql.err.ProgrammingError(1146, "Table doesn't exist")
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = get_applied_patches(conn, "jira")

        assert result == set()


class TestGetAllApplied:
    def test_returns_fully_qualified_names(self):
        conn, _ = _mock_conn(fetchall_return=[
            {"module": "jira", "name": "PopulateDefaults"},
            {"module": "claude", "name": "SeedTokens"},
        ])

        result = get_all_applied(conn)

        assert result == {"jira/PopulateDefaults", "claude/SeedTokens"}


class TestGetAllPending:
    def test_excludes_already_applied(self):
        conn, _ = _mock_conn(fetchall_return=[
            {"module": "jira", "name": "PopulateDefaults"},
        ])

        m = ModuleManifest(
            name="jira", version="1.0.0", description="", path=Path("/fake"),
            data_patches={"patches": [
                {"name": "PopulateDefaults", "class": "src.patches.populate.PopulateDefaults"},
                {"name": "SeedData", "class": "src.patches.seed.SeedData"},
            ]},
        )

        pending = get_all_pending([m], conn)

        assert len(pending) == 1
        assert pending[0][1]["name"] == "SeedData"

    def test_empty_when_all_applied(self):
        conn, _ = _mock_conn(fetchall_return=[
            {"module": "jira", "name": "PopulateDefaults"},
        ])

        m = ModuleManifest(
            name="jira", version="1.0.0", description="", path=Path("/fake"),
            data_patches={"patches": [
                {"name": "PopulateDefaults", "class": "src.patches.populate.PopulateDefaults"},
            ]},
        )

        assert get_all_pending([m], conn) == []

    def test_empty_when_no_patches_declared(self):
        conn, _ = _mock_conn()

        m = ModuleManifest(
            name="jira", version="1.0.0", description="", path=Path("/fake"),
        )

        assert get_all_pending([m], conn) == []


class TestResolvePatchOrder:
    def test_no_dependencies_preserves_order(self, tmp_path):
        m = _make_manifest(tmp_path, "jira", [
            {"name": "First", "class": "src.patches.first.First"},
            {"name": "Second", "class": "src.patches.second.Second"},
        ])

        result = resolve_patch_order([(m, m.data_patches["patches"][0]), (m, m.data_patches["patches"][1])])

        assert [p["name"] for _, p in result] == ["First", "Second"]

    def test_require_orders_correctly(self, tmp_path):
        m = _make_manifest(tmp_path, "jira", [
            {"name": "B", "class": "src.patches.b.B", "_require": ["jira/A"]},
            {"name": "A", "class": "src.patches.a.A"},
        ])

        pending = [(m, m.data_patches["patches"][0]), (m, m.data_patches["patches"][1])]
        result = resolve_patch_order(pending)

        names = [p["name"] for _, p in result]
        assert names.index("A") < names.index("B")

    def test_cross_module_require(self, tmp_path):
        m1 = _make_manifest(tmp_path, "core", [
            {"name": "CoreSetup", "class": "src.patches.core_setup.CoreSetup"},
        ])
        m2 = _make_manifest(tmp_path, "jira", [
            {"name": "JiraSetup", "class": "src.patches.jira_setup.JiraSetup", "_require": ["core/CoreSetup"]},
        ])

        pending = [
            (m2, m2.data_patches["patches"][0]),
            (m1, m1.data_patches["patches"][0]),
        ]
        result = resolve_patch_order(pending)

        names = [f"{m.name}/{p['name']}" for m, p in result]
        assert names.index("core/CoreSetup") < names.index("jira/JiraSetup")

    def test_cycle_detection(self, tmp_path):
        m = _make_manifest(tmp_path, "jira", [
            {"name": "A", "class": "src.patches.a.A", "_require": ["jira/B"]},
            {"name": "B", "class": "src.patches.b.B", "_require": ["jira/A"]},
        ])

        pending = [(m, m.data_patches["patches"][0]), (m, m.data_patches["patches"][1])]

        with pytest.raises(CyclicPatchDependencyError):
            resolve_patch_order(pending)

    def test_empty_pending(self):
        assert resolve_patch_order([]) == []


class TestApplyPatch:
    def test_applies_and_records(self, tmp_path):
        m = _make_manifest(tmp_path, "jira", [
            {"name": "PopulateDefaults", "class": "src.patches.populate.PopulateDefaults"},
        ])
        conn, cursor = _mock_conn()
        logger = MagicMock()

        apply_patch(m, m.data_patches["patches"][0], conn, logger)

        # INSERT into data_patch
        insert_call = cursor.execute.call_args_list[-1]
        assert "data_patch" in insert_call[0][0]
        assert insert_call[0][1] == ("PopulateDefaults", "jira")
        conn.commit.assert_called_once()
        logger.info.assert_called_once()

    def test_dispatches_data_patch_applied_event(self, tmp_path):
        clear_event_manager()

        class Collector:
            events: list = []  # noqa: RUF012

            def execute(self, event: object) -> None:
                Collector.events.append(event)

        Collector.events = []

        em = get_event_manager()
        em.register("data_patch_apply_after", ObserverEntry(name="dp", observer_class=Collector))

        m = _make_manifest(tmp_path, "jira", [
            {"name": "PopulateDefaults", "class": "src.patches.populate.PopulateDefaults"},
        ])
        conn, _ = _mock_conn()

        apply_patch(m, m.data_patches["patches"][0], conn, MagicMock())

        assert len(Collector.events) == 1
        evt = Collector.events[0]
        assert isinstance(evt, DataPatchAppliedEvent)
        assert evt.name == "PopulateDefaults"
        assert evt.module == "jira"

        clear_event_manager()
