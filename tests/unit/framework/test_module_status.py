"""Tests for module_status — file-based enable/disable state."""
from __future__ import annotations

import json
from pathlib import Path

from agento.framework.module_loader import ModuleManifest
from agento.framework.module_status import (
    filter_enabled,
    is_enabled,
    read_module_status,
    resolve_module_source,
    set_enabled,
    write_module_status,
)


def _m(name: str, **kwargs) -> ModuleManifest:
    return ModuleManifest(
        name=name, version="1.0.0", description="", path=Path(f"/fake/{name}"), **kwargs
    )


class TestReadModuleStatus:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert read_module_status(tmp_path / "nope.json") == {}

    def test_reads_valid_file(self, tmp_path: Path):
        p = tmp_path / "modules.json"
        p.write_text(json.dumps({"jira": True, "codex": False}))
        assert read_module_status(p) == {"jira": True, "codex": False}

    def test_invalid_json_returns_empty(self, tmp_path: Path):
        p = tmp_path / "modules.json"
        p.write_text("{bad")
        assert read_module_status(p) == {}


class TestWriteModuleStatus:
    def test_writes_file(self, tmp_path: Path):
        p = tmp_path / "modules.json"
        write_module_status({"a": True, "b": False}, p)
        assert json.loads(p.read_text()) == {"a": True, "b": False}

    def test_creates_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "sub" / "dir" / "modules.json"
        write_module_status({"x": True}, p)
        assert p.is_file()


class TestIsEnabled:
    def test_default_true_when_not_in_status(self):
        assert is_enabled("unknown", {}) is True

    def test_explicit_true(self):
        assert is_enabled("jira", {"jira": True}) is True

    def test_explicit_false(self):
        assert is_enabled("codex", {"codex": False}) is False


class TestSetEnabled:
    def test_set_enabled_writes(self, tmp_path: Path):
        p = tmp_path / "modules.json"
        set_enabled("codex", False, p)
        assert json.loads(p.read_text()) == {"codex": False}

    def test_preserves_existing(self, tmp_path: Path):
        p = tmp_path / "modules.json"
        p.write_text(json.dumps({"jira": True}))
        set_enabled("codex", False, p)
        data = json.loads(p.read_text())
        assert data == {"jira": True, "codex": False}


class TestFilterEnabled:
    def test_removes_disabled(self, tmp_path: Path):
        p = tmp_path / "modules.json"
        p.write_text(json.dumps({"b": False}))
        manifests = [_m("a"), _m("b"), _m("c")]
        result = filter_enabled(manifests, p)
        assert [m.name for m in result] == ["a", "c"]

    def test_all_enabled_by_default(self, tmp_path: Path):
        p = tmp_path / "modules.json"  # doesn't exist
        manifests = [_m("a"), _m("b")]
        result = filter_enabled(manifests, p)
        assert [m.name for m in result] == ["a", "b"]


class TestResolveModuleSource:
    def test_local_module_takes_precedence(self, tmp_path: Path):
        # Both app/code/<name>/ AND venv install — local wins.
        local = tmp_path / "app" / "code" / "k3_jira"
        local.mkdir(parents=True)
        (local / "module.json").write_text("{}")

        site = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages" / "k3_jira"
        site.mkdir(parents=True)
        (site / "__init__.py").write_text("")

        assert resolve_module_source("k3_jira", tmp_path) == "local"

    def test_pypi_extension(self, tmp_path: Path):
        site = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages" / "agento_ext"
        site.mkdir(parents=True)
        (site / "__init__.py").write_text("")

        assert resolve_module_source("agento_ext", tmp_path) == "pypi"

    def test_pypi_under_alternate_python_minor(self, tmp_path: Path):
        # detect_python_version may pick a different minor — resolver globs
        # python*/site-packages so it must still find the package.
        site = tmp_path / ".venv" / "lib" / "python3.13" / "site-packages" / "agento_ext"
        site.mkdir(parents=True)
        (site / "__init__.py").write_text("")

        assert resolve_module_source("agento_ext", tmp_path) == "pypi"

    def test_missing_module(self, tmp_path: Path):
        assert resolve_module_source("ghost", tmp_path) == "missing"

    def test_module_dir_without_init_is_not_pypi(self, tmp_path: Path):
        # An empty package directory (no __init__.py) does not count.
        (tmp_path / ".venv" / "lib" / "python3.12" / "site-packages" / "halfbaked").mkdir(parents=True)
        assert resolve_module_source("halfbaked", tmp_path) == "missing"
