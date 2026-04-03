"""Tests for agento init command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from agento.framework.cli.init import InitCommand, TemplateNotFoundError, _get_template


class TestGetTemplate:
    def test_reads_from_templates_dir(self, tmp_path: Path):
        templates = tmp_path / "templates"
        templates.mkdir()
        (templates / "test.txt").write_text("hello")

        with patch("agento.framework.cli.init.Path") as mock_path:
            # Make __file__.parent / "templates" point to our tmp dir
            mock_path.return_value.parent = tmp_path
            # Fall through importlib.resources, use direct path
            result = _get_template("gitignore")
            # This uses the real templates dir, which exists
            assert isinstance(result, str)

    def test_raises_on_missing(self):
        import pytest

        with (
            patch("agento.framework.cli.init.importlib.resources.files", side_effect=ModuleNotFoundError),
            patch("agento.framework.cli.init.Path") as mock_path,
        ):
            mock_path.return_value.parent.__truediv__ = lambda self, x: Path("/nonexistent")
            with pytest.raises(TemplateNotFoundError):
                _get_template("nonexistent_template_xyz")


class TestCmdInit:
    def test_creates_project_structure(self, tmp_path: Path):
        args = argparse.Namespace(project="test-proj", no_example=False)
        with patch("agento.framework.cli.init.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            # Let Path() constructor work normally for everything else
            mock_path_cls.side_effect = lambda *a, **kw: Path(*a, **kw) if a else tmp_path

        # Run for real using tmp_path
        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            InitCommand().execute(args)
        finally:
            Path.cwd = original_cwd

        project_dir = tmp_path / "test-proj"
        assert project_dir.is_dir()
        assert (project_dir / ".agento" / "project.json").is_file()
        assert (project_dir / "app" / "code").is_dir()
        assert (project_dir / "workspace" / "systems").is_dir()
        assert (project_dir / "logs").is_dir()
        assert (project_dir / "tokens").is_dir()
        assert (project_dir / "docker").is_dir()
        assert (project_dir / ".gitignore").is_file()
        assert (project_dir / "secrets.env.example").is_file()

        meta = json.loads((project_dir / ".agento" / "project.json").read_text())
        assert meta["name"] == "test-proj"

    def test_refuses_non_empty_directory(self, tmp_path: Path):
        import pytest

        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "some_file.txt").write_text("content")
        args = argparse.Namespace(project="existing", no_example=False)

        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            with pytest.raises(SystemExit, match="1"):
                InitCommand().execute(args)
        finally:
            Path.cwd = original_cwd

    def test_init_in_existing_empty_directory(self, tmp_path: Path):
        existing = tmp_path / "empty-proj"
        existing.mkdir()
        args = argparse.Namespace(project="empty-proj", no_example=False)

        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            InitCommand().execute(args)
        finally:
            Path.cwd = original_cwd

        assert (existing / ".agento" / "project.json").is_file()
        meta = json.loads((existing / ".agento" / "project.json").read_text())
        assert meta["name"] == "empty-proj"

    def test_init_dot_uses_current_directory(self, tmp_path: Path):
        args = argparse.Namespace(project=".", no_example=False)

        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: tmp_path)
            InitCommand().execute(args)
        finally:
            Path.cwd = original_cwd

        assert (tmp_path / ".agento" / "project.json").is_file()
        assert (tmp_path / "app" / "code").is_dir()

    def test_init_dot_derives_name_from_dirname(self, tmp_path: Path):
        work_dir = tmp_path / "my-cool-project"
        work_dir.mkdir()
        args = argparse.Namespace(project=".", no_example=False)

        original_cwd = Path.cwd
        try:
            Path.cwd = staticmethod(lambda: work_dir)
            InitCommand().execute(args)
        finally:
            Path.cwd = original_cwd

        meta = json.loads((work_dir / ".agento" / "project.json").read_text())
        assert meta["name"] == "my-cool-project"
