"""Tests for module validation."""
from __future__ import annotations

import json
from pathlib import Path

from agento.framework.module_validator import validate_module

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DIR = ROOT / "app" / "code" / "_example"


class TestValidateModule:
    def test_valid_module_passes(self, tmp_path: Path):
        mod = tmp_path / "good"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({
            "name": "good",
            "version": "1.0.0",
            "description": "A good module",
            "tools": [],
            "log_servers": [],
        }))
        (mod / "config.json").write_text("{}")

        errors = validate_module(mod)
        assert errors == []

    def test_missing_module_json(self, tmp_path: Path):
        mod = tmp_path / "empty"
        mod.mkdir()

        errors = validate_module(mod)
        assert any("module.json not found" in e for e in errors)

    def test_missing_required_fields(self, tmp_path: Path):
        mod = tmp_path / "incomplete"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({"name": "incomplete"}))

        errors = validate_module(mod)
        assert any("version" in e for e in errors)
        assert any("description" in e for e in errors)

    def test_invalid_di_json_class(self, tmp_path: Path):
        mod = tmp_path / "bad-di"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({
            "name": "bad-di",
            "version": "1.0.0",
            "description": "Bad DI",
            "tools": [],
        }))
        (mod / "di.json").write_text(json.dumps({
            "commands": [{"class": "src.commands.nonexistent.FakeCommand"}],
        }))

        errors = validate_module(mod)
        assert any("does not resolve" in e for e in errors)

    def test_example_module_valid(self):
        """The actual _example module should pass validation."""
        errors = validate_module(EXAMPLE_DIR)
        assert errors == [], f"Example module errors: {errors}"

    def test_invalid_json_file(self, tmp_path: Path):
        mod = tmp_path / "bad-json"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({
            "name": "bad-json",
            "version": "1.0.0",
            "description": "Bad JSON",
            "tools": [],
        }))
        (mod / "config.json").write_text("{invalid json")

        errors = validate_module(mod)
        assert any("config.json" in e for e in errors)
