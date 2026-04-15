"""Data patch: flatten legacy ``workspace/theme/_root`` layout.

Before this release the theme layered overlays were rooted at
``workspace/theme/_root/`` with workspace and agent_view overlays nested
beneath. The wrapper is redundant — module workspaces already use the flat
``{base}/`` + ``{base}/_{ws}/`` + ``{base}/_{ws}/_{av}/`` cascade. This patch
migrates existing deployments to the flat layout so ``_copy_theme`` can read
from ``workspace/theme/`` directly.

Behaviour:
- If ``_root/`` is absent AND no obsolete files exist at theme root, no-op
  (fresh install or already migrated).
- Obsolete reference files at theme root (``*.template``) are deleted — the
  pre-flatten docs marked them "not copied to builds", so post-flatten they
  would silently leak in.
- Each item under ``_root/`` moves up one level into ``workspace/theme/``.
  If a name conflict exists at the destination (unexpected — would require
  operator intervention), the move is skipped and a warning is logged.
- If ``_root/`` is empty afterwards it's removed; otherwise it's renamed to
  ``_root.migrated`` for operator inspection.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Filename suffixes that are obsolete under the flat layout.
_OBSOLETE_SUFFIXES = (".template",)


def _migrate(theme_dir: Path) -> None:
    if not theme_dir.is_dir():
        return

    # Delete obsolete reference files at theme root regardless of whether
    # _root/ exists — covers the case where _root/ was removed manually but
    # the reference templates were left behind.
    for item in list(theme_dir.iterdir()):
        if item.name.startswith((".", "_")):
            continue
        if item.is_file() and item.name.endswith(_OBSOLETE_SUFFIXES):
            logger.info("Removing obsolete theme file %s", item)
            item.unlink()

    root_legacy = theme_dir / "_root"
    if not root_legacy.is_dir():
        return

    for item in list(root_legacy.iterdir()):
        dest = theme_dir / item.name
        if dest.exists():
            logger.warning(
                "Skipping %s: destination %s already exists \u2014 resolve manually",
                item, dest,
            )
            continue
        shutil.move(str(item), str(dest))

    try:
        root_legacy.rmdir()
        logger.info("Removed empty %s after flatten", root_legacy)
    except OSError:
        migrated = theme_dir / "_root.migrated"
        if migrated.exists():
            n = 1
            while (theme_dir / f"_root.migrated.{n}").exists():
                n += 1
            migrated = theme_dir / f"_root.migrated.{n}"
        root_legacy.rename(migrated)
        logger.warning(
            "Theme flatten left leftovers in %s \u2014 renamed to %s for inspection",
            root_legacy, migrated,
        )


class FlattenThemeRoot:
    """Move ``workspace/theme/_root/*`` up to ``workspace/theme/``."""

    def apply(self, conn) -> None:  # conn unused — filesystem-only patch
        from agento.framework.workspace_paths import THEME_DIR

        _migrate(Path(THEME_DIR))

    def require(self) -> list[str]:
        return []
