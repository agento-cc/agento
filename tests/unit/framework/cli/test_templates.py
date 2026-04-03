"""Tests for template loading utilities."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agento.framework.cli._templates import TemplateNotFoundError, get_template


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
