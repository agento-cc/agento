"""Observers for the workspace_build module."""
from __future__ import annotations

import logging
from pathlib import Path

from agento.framework.config_writer import get_config_writer
from agento.framework.workspace_paths import BUILD_DIR

logger = logging.getLogger(__name__)


class RefreshBuildCredentialsObserver:
    """Re-materialize provider credentials into every existing ``current`` build.

    Fires on ``token_refresh_after`` and ``token_register_after``. Without this,
    ``workspace/build/<ws>/<av>/current/<provider>/...credentials`` keeps the
    pre-refresh token that the Anthropic/OpenAI server has already invalidated,
    so ``agento run`` falls back to an interactive login prompt.

    Only touches the provider that the event is about — a Claude refresh does
    not rewrite Codex auth files and vice versa.
    """

    def execute(self, event) -> None:
        agent_type = getattr(event, "agent_type", None)
        credentials = getattr(event, "credentials", None)
        if not agent_type or not credentials:
            return

        try:
            writer = get_config_writer(agent_type)
        except (KeyError, ValueError):
            logger.debug(
                "No ConfigWriter for provider %s; nothing to re-materialize.",
                agent_type,
            )
            return

        build_root = Path(BUILD_DIR)
        if not build_root.is_dir():
            return

        updated = 0
        for current in build_root.glob("*/*/current"):
            try:
                target = current.resolve(strict=True)
            except (FileNotFoundError, OSError):
                continue
            if not target.is_dir():
                continue
            try:
                writer.write_credentials(target, credentials)
                updated += 1
                logger.info(
                    "Refreshed %s credentials in build dir: %s",
                    agent_type, target,
                )
            except Exception:
                logger.warning(
                    "Failed to refresh %s credentials in build dir: %s",
                    agent_type, target, exc_info=True,
                )

        if updated:
            logger.info(
                "Refreshed %s credentials across %d build dir(s).",
                agent_type, updated,
            )
