"""Tests for the FlattenThemeRoot data patch."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agento.modules.workspace_build.src.patches.flatten_theme_root import (
    FlattenThemeRoot,
    _migrate,
)


class TestFlattenThemeRoot:
    def test_noop_when_theme_missing(self, tmp_path):
        """Theme dir absent: nothing to do, no crash."""
        theme = tmp_path / "nope"
        _migrate(theme)
        assert not theme.exists()

    def test_noop_when_already_flat(self, tmp_path):
        """No _root/, no obsolete files: leaves a flat layout untouched."""
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "SOUL.md").write_text("already flat")
        _migrate(theme)
        assert (theme / "SOUL.md").read_text() == "already flat"

    def test_moves_root_contents_up_and_removes_wrapper(self, tmp_path):
        theme = tmp_path / "theme"
        root = theme / "_root"
        root.mkdir(parents=True)
        (root / "SOUL.md").write_text("# soul")
        (root / "CLAUDE.md").write_text("# claude")
        (root / "app").mkdir()
        (root / "app" / "data.txt").write_text("data")

        _migrate(theme)

        assert not root.exists(), "_root should have been removed after migration"
        assert (theme / "SOUL.md").read_text() == "# soul"
        assert (theme / "CLAUDE.md").read_text() == "# claude"
        assert (theme / "app" / "data.txt").read_text() == "data"

    def test_deletes_obsolete_template_files(self, tmp_path):
        """Stray ``*.template`` files at theme root are deleted outright."""
        theme = tmp_path / "theme"
        root = theme / "_root"
        root.mkdir(parents=True)
        (root / "SOUL.md").write_text("# soul")
        (theme / "AGENTS.md.template").write_text("obsolete ref")
        (theme / "SOUL.md.template").write_text("obsolete ref")

        _migrate(theme)

        assert not (theme / "AGENTS.md.template").exists()
        assert not (theme / "SOUL.md.template").exists()
        assert not (theme / ".legacy").exists()
        assert (theme / "SOUL.md").read_text() == "# soul"

    def test_deletes_template_files_when_root_already_gone(self, tmp_path):
        """Operator deleted _root manually but left .template files \u2014 still cleaned up."""
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "SOUL.md").write_text("# already flat")
        (theme / "AGENTS.md.template").write_text("obsolete")

        _migrate(theme)

        assert (theme / "SOUL.md").read_text() == "# already flat"
        assert not (theme / "AGENTS.md.template").exists()
        assert not (theme / ".legacy").exists()

    def test_preserves_workspace_overlays_under_root(self, tmp_path):
        """``_root/_myws/_myav/`` should migrate to ``_myws/_myav/`` (structure preserved)."""
        theme = tmp_path / "theme"
        root = theme / "_root"
        root.mkdir(parents=True)
        ws = root / "_myws"
        ws.mkdir()
        (ws / "ws_note.md").write_text("ws layer")
        av = ws / "_myav"
        av.mkdir()
        (av / "av_note.md").write_text("av layer")

        _migrate(theme)

        assert (theme / "_myws" / "ws_note.md").read_text() == "ws layer"
        assert (theme / "_myws" / "_myav" / "av_note.md").read_text() == "av layer"
        assert not root.exists()

    def test_skips_conflicting_move_and_parks_leftovers(self, tmp_path):
        """Unexpected destination conflict: skip the move, log, rename _root \u2192 _root.migrated."""
        theme = tmp_path / "theme"
        root = theme / "_root"
        root.mkdir(parents=True)
        (root / "SOUL.md").write_text("from _root")
        # Pre-existing file at destination with no .template suffix \u2014 not auto-deleted.
        (theme / "SOUL.md").write_text("pre-existing")

        _migrate(theme)

        # Existing file preserved, _root migrated for inspection.
        assert (theme / "SOUL.md").read_text() == "pre-existing"
        assert not root.exists()
        assert (theme / "_root.migrated" / "SOUL.md").read_text() == "from _root"

    def test_idempotent_when_run_twice(self, tmp_path):
        theme = tmp_path / "theme"
        root = theme / "_root"
        root.mkdir(parents=True)
        (root / "SOUL.md").write_text("# soul")

        _migrate(theme)
        _migrate(theme)  # second run: no _root, should be a no-op

        assert (theme / "SOUL.md").read_text() == "# soul"

    def test_apply_resolves_theme_dir_from_workspace_paths(self, tmp_path):
        """The data-patch wrapper reads THEME_DIR dynamically, not at import time."""
        theme = tmp_path / "theme"
        root = theme / "_root"
        root.mkdir(parents=True)
        (root / "SOUL.md").write_text("# soul")

        with patch("agento.framework.workspace_paths.THEME_DIR", str(theme)):
            FlattenThemeRoot().apply(MagicMock())

        assert (theme / "SOUL.md").read_text() == "# soul"
        assert not root.exists()

    def test_require_returns_empty_list(self):
        assert FlattenThemeRoot().require() == []
