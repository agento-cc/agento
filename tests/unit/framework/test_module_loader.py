"""Tests for module_loader — scanning manifests and importing classes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agento.framework.module_loader import import_class, scan_modules


class TestScanModules:
    def test_empty_dir(self, tmp_path: Path):
        assert scan_modules(str(tmp_path)) == []

    def test_nonexistent_dir(self, tmp_path: Path):
        assert scan_modules(str(tmp_path / "nope")) == []

    def test_skips_underscore_dirs(self, tmp_path: Path):
        example = tmp_path / "_example"
        example.mkdir()
        (example / "module.json").write_text(json.dumps({"name": "_example"}))
        assert scan_modules(str(tmp_path)) == []

    def test_skips_dirs_without_manifest(self, tmp_path: Path):
        (tmp_path / "empty_mod").mkdir()
        assert scan_modules(str(tmp_path)) == []

    def test_basic_manifest(self, tmp_path: Path):
        mod_dir = tmp_path / "jira"
        mod_dir.mkdir()
        manifest = {
            "name": "jira",
            "version": "1.0.0",
            "description": "Jira integration",
            "provides": {
                "channels": [{"name": "jira", "class": "src.channel.JiraChannel"}],
            },
            "tools": [{"type": "mysql", "name": "mysql_jira"}],
        }
        (mod_dir / "module.json").write_text(json.dumps(manifest))

        result = scan_modules(str(tmp_path))
        assert len(result) == 1
        assert result[0].name == "jira"
        assert result[0].version == "1.0.0"
        assert result[0].path == mod_dir
        assert len(result[0].provides["channels"]) == 1
        assert len(result[0].tools) == 1

    def test_sorted_by_name(self, tmp_path: Path):
        for name in ["beta", "alpha"]:
            d = tmp_path / name
            d.mkdir()
            (d / "module.json").write_text(json.dumps({"name": name}))

        result = scan_modules(str(tmp_path))
        assert [m.name for m in result] == ["alpha", "beta"]

    def test_defaults_for_missing_fields(self, tmp_path: Path):
        mod_dir = tmp_path / "minimal"
        mod_dir.mkdir()
        (mod_dir / "module.json").write_text(json.dumps({"name": "minimal"}))

        result = scan_modules(str(tmp_path))
        assert result[0].version == "0.0.0"
        assert result[0].description == ""
        assert result[0].provides == {}
        assert result[0].tools == []
        assert result[0].log_servers == []


class TestCompanionFiles:
    def test_reads_data_patch_json(self, tmp_path: Path):
        mod_dir = tmp_path / "jira"
        mod_dir.mkdir()
        (mod_dir / "module.json").write_text(json.dumps({"name": "jira"}))
        (mod_dir / "data_patch.json").write_text(json.dumps({
            "patches": [{"name": "PopulateDefaults", "class": "src.patches.PopulateDefaults"}]
        }))

        result = scan_modules(str(tmp_path))
        assert result[0].data_patches["patches"][0]["name"] == "PopulateDefaults"

    def test_reads_cron_json(self, tmp_path: Path):
        mod_dir = tmp_path / "jira"
        mod_dir.mkdir()
        (mod_dir / "module.json").write_text(json.dumps({"name": "jira"}))
        (mod_dir / "cron.json").write_text(json.dumps({
            "jobs": [{"name": "sync", "schedule": "0 * * * *", "command": "sync"}]
        }))

        result = scan_modules(str(tmp_path))
        assert result[0].cron["jobs"][0]["name"] == "sync"

    def test_falls_back_to_inline_data_patches(self, tmp_path: Path):
        mod_dir = tmp_path / "jira"
        mod_dir.mkdir()
        (mod_dir / "module.json").write_text(json.dumps({
            "name": "jira",
            "data_patches": {"patches": [{"name": "Inline"}]},
        }))

        result = scan_modules(str(tmp_path))
        assert result[0].data_patches["patches"][0]["name"] == "Inline"

    def test_defaults_to_empty_dict(self, tmp_path: Path):
        mod_dir = tmp_path / "minimal"
        mod_dir.mkdir()
        (mod_dir / "module.json").write_text(json.dumps({"name": "minimal"}))

        result = scan_modules(str(tmp_path))
        assert result[0].data_patches == {}
        assert result[0].cron == {}


class TestImportClass:
    def test_import_simple_class(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "greeting.py").write_text(
            "class Hello:\n    msg = 'hi'\n"
        )
        cls = import_class(tmp_path, "src.greeting.Hello")
        assert cls.msg == "hi"

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="Module file not found"):
            import_class(tmp_path, "src.nope.Missing")

    def test_class_not_found(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "empty.py").write_text("")
        with pytest.raises(AttributeError, match="does not define"):
            import_class(tmp_path, "src.empty.Missing")

    def test_invalid_class_path(self, tmp_path: Path):
        with pytest.raises(ValueError, match="must be"):
            import_class(tmp_path, "NoDotsHere")

    def test_nested_module(self, tmp_path: Path):
        nested = tmp_path / "src" / "workflows"
        nested.mkdir(parents=True)
        (nested / "cron.py").write_text(
            "class CronWorkflow:\n    kind = 'cron'\n"
        )
        cls = import_class(tmp_path, "src.workflows.cron.CronWorkflow")
        assert cls.kind == "cron"
