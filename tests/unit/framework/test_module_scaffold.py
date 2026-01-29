"""Tests for module scaffolding."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agento.framework.module_scaffold import scaffold_module


class TestScaffoldModule:
    def test_creates_directory_structure(self, tmp_path: Path):
        module_dir = scaffold_module("test-mod", tmp_path)

        assert module_dir.is_dir()
        assert (module_dir / "module.json").is_file()
        assert (module_dir / "config.json").is_file()
        assert (module_dir / "di.json").is_file()
        assert (module_dir / "events.json").is_file()
        assert (module_dir / "data_patch.json").is_file()
        assert (module_dir / "cron.json").is_file()
        assert (module_dir / "knowledge" / "README.md").is_file()
        assert (module_dir / "src" / "__init__.py").is_file()

    def test_generates_valid_module_json(self, tmp_path: Path):
        module_dir = scaffold_module("my-app", tmp_path, description="My App")

        manifest = json.loads((module_dir / "module.json").read_text())
        assert manifest["name"] == "my-app"
        assert manifest["version"] == "1.0.0"
        assert manifest["description"] == "My App"
        assert manifest["tools"] == []
        assert manifest["log_servers"] == []

    def test_with_tools(self, tmp_path: Path):
        module_dir = scaffold_module(
            "db-app", tmp_path,
            tools=["mysql:mysql_prod:Production DB"],
        )

        manifest = json.loads((module_dir / "module.json").read_text())
        assert len(manifest["tools"]) == 1
        tool = manifest["tools"][0]
        assert tool["type"] == "mysql"
        assert tool["name"] == "mysql_prod"
        assert tool["description"] == "Production DB"
        assert "host" in tool["fields"]
        assert tool["fields"]["pass"]["type"] == "obscure"

        config = json.loads((module_dir / "config.json").read_text())
        assert "tools" in config
        assert "mysql_prod" in config["tools"]

    def test_rejects_invalid_name(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Invalid module name"):
            scaffold_module("MyApp", tmp_path)
        with pytest.raises(ValueError, match="Invalid module name"):
            scaffold_module("_private", tmp_path)
        with pytest.raises(ValueError, match="Invalid module name"):
            scaffold_module("has spaces", tmp_path)

    def test_rejects_existing_directory(self, tmp_path: Path):
        (tmp_path / "existing").mkdir()
        with pytest.raises(ValueError, match="already exists"):
            scaffold_module("existing", tmp_path)

    def test_companion_files_valid_json(self, tmp_path: Path):
        module_dir = scaffold_module("check-json", tmp_path)

        for filename in ("di.json", "events.json", "data_patch.json", "cron.json"):
            data = json.loads((module_dir / filename).read_text())
            assert isinstance(data, dict)
