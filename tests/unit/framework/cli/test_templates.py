"""Tests for template loading utilities."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agento.framework.cli._templates import (
    TemplateNotFoundError,
    extract_sql_files,
    get_package_version,
    get_template,
)


class TestGetTemplate:
    def test_reads_existing_template(self):
        result = get_template("gitignore")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_raises_on_missing_template(self):
        with (
            patch("agento.framework.cli._templates.importlib.resources.files", side_effect=ModuleNotFoundError),
            patch("agento.framework.cli._templates.Path") as mock_path,
        ):
            mock_path.return_value.parent.__truediv__ = lambda self, x: Path("/nonexistent")
            with pytest.raises(TemplateNotFoundError):
                get_template("nonexistent_template_xyz")


class TestGetPackageVersion:
    def test_returns_version_string(self):
        version = get_package_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_fallback_to_latest(self):
        from importlib.metadata import PackageNotFoundError

        with patch("importlib.metadata.version", side_effect=PackageNotFoundError):
            assert get_package_version() == "latest"


class TestExtractSqlFiles:
    def test_extracts_sql_files(self, tmp_path: Path):
        target = tmp_path / "sql"
        extract_sql_files(target)
        sql_files = list(target.glob("*.sql"))
        assert len(sql_files) > 0
        # Verify they're actual SQL content
        for f in sql_files:
            content = f.read_text()
            assert len(content) > 0

    def test_creates_target_dir(self, tmp_path: Path):
        target = tmp_path / "nested" / "sql"
        extract_sql_files(target)
        assert target.is_dir()
