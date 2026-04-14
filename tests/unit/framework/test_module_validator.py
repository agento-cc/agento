"""Tests for module validation."""
from __future__ import annotations

import json
from pathlib import Path

from agento.framework.module_validator import validate_all, validate_module

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

    def test_sequence_not_a_list(self, tmp_path: Path):
        mod = tmp_path / "bad-seq"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({
            "name": "bad-seq",
            "version": "1.0.0",
            "description": "Bad sequence",
            "sequence": "not-a-list",
        }))
        errors = validate_module(mod)
        assert any("'sequence' must be an array" in e for e in errors)

    def test_sequence_entry_not_string(self, tmp_path: Path):
        mod = tmp_path / "bad-entry"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({
            "name": "bad-entry",
            "version": "1.0.0",
            "description": "Bad entry",
            "sequence": [123],
        }))
        errors = validate_module(mod)
        assert any("must be strings" in e for e in errors)

    def test_valid_sequence(self, tmp_path: Path):
        mod = tmp_path / "good-seq"
        mod.mkdir()
        (mod / "module.json").write_text(json.dumps({
            "name": "good-seq",
            "version": "1.0.0",
            "description": "Good sequence",
            "sequence": ["core"],
        }))
        errors = validate_module(mod)
        assert errors == []

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


class TestSelectFieldValidation:
    """Validation of select/multiselect fields with options."""

    def _make_module(self, tmp_path: Path, system: dict) -> Path:
        mod = tmp_path / "sel"
        mod.mkdir(exist_ok=True)
        (mod / "module.json").write_text(json.dumps({
            "name": "sel", "version": "1.0.0", "description": "Select test",
        }))
        (mod / "system.json").write_text(json.dumps(system))
        return mod

    def test_select_field_requires_options(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "strategy": {"type": "select", "label": "Strategy"},
        })
        errors = validate_module(mod)
        assert any("requires 'options'" in e for e in errors)

    def test_multiselect_field_requires_options(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "tags": {"type": "multiselect", "label": "Tags"},
        })
        errors = validate_module(mod)
        assert any("requires 'options'" in e for e in errors)

    def test_select_field_with_valid_options_passes(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "strategy": {
                "type": "select", "label": "Strategy",
                "options": [
                    {"value": "copy", "label": "Copy"},
                    {"value": "symlink", "label": "Symlink"},
                ],
            },
        })
        errors = validate_module(mod)
        assert errors == []

    def test_select_option_missing_value_or_label(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "strategy": {
                "type": "select", "label": "Strategy",
                "options": [{"value": "copy"}],
            },
        })
        errors = validate_module(mod)
        assert any("must have 'value' and 'label'" in e for e in errors)

    def test_select_option_not_an_object(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "strategy": {
                "type": "select", "label": "Strategy",
                "options": ["copy", "symlink"],
            },
        })
        errors = validate_module(mod)
        assert any("must be an object" in e for e in errors)

    def test_options_on_non_select_type_errors(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "name": {
                "type": "string", "label": "Name",
                "options": [{"value": "a", "label": "A"}],
            },
        })
        errors = validate_module(mod)
        assert any("only select/multiselect support options" in e for e in errors)

    def test_options_not_a_list_errors(self, tmp_path: Path):
        mod = self._make_module(tmp_path, {
            "strategy": {
                "type": "select", "label": "Strategy",
                "options": "invalid",
            },
        })
        errors = validate_module(mod)
        assert any("options must be an array" in e for e in errors)


class TestValidateAllSequenceCross:
    """Cross-module sequence validation: deps must exist on disk."""

    def _make_module(self, parent: Path, name: str, sequence: list[str] | None = None):
        mod = parent / name
        mod.mkdir()
        manifest = {"name": name, "version": "1.0.0", "description": f"{name} module"}
        if sequence is not None:
            manifest["sequence"] = sequence
        (mod / "module.json").write_text(json.dumps(manifest))

    def test_missing_sequence_dep_flagged(self, tmp_path: Path):
        core = tmp_path / "core_mods"
        core.mkdir()
        self._make_module(core, "a", sequence=["nonexistent"])
        results = validate_all(core, tmp_path / "empty")
        assert "a" in results
        assert any("nonexistent" in e and "not found" in e for e in results["a"])

    def test_valid_sequence_dep_passes(self, tmp_path: Path):
        core = tmp_path / "core_mods"
        core.mkdir()
        self._make_module(core, "base")
        self._make_module(core, "child", sequence=["base"])
        results = validate_all(core, tmp_path / "empty")
        assert "child" not in results
