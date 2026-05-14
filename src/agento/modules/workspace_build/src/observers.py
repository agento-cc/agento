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


class ReplaceErroredTokenCredentialsObserver:
    """When a token for ``agent_type`` flips to ``status='error'``, re-materialize
    every existing ``current`` build dir with the next LRU healthy token for the
    same provider.

    Fires on ``token_auth_failed_after`` (dispatched by both the consumer's
    auth-failure path and the manual ``token:mark-error`` CLI). Without this,
    builds keep the dead refresh-token from the errored row and every
    subsequent ``agento run`` fails with the same auth error.

    Skips silently when no healthy alternative exists for that provider — the
    next ``workspace:build`` will surface the "no healthy tokens" diagnostic
    from ``TokenResolver``.
    """

    def execute(self, event) -> None:
        agent_type = getattr(event, "agent_type", None)
        if not agent_type:
            return

        try:
            writer = get_config_writer(agent_type)
        except (KeyError, ValueError):
            logger.debug(
                "No ConfigWriter for provider %s; nothing to re-materialize.",
                agent_type,
            )
            return

        from agento.framework.agent_manager.models import AgentProvider
        from agento.framework.agent_manager.token_resolver import TokenResolver
        from agento.framework.database_config import DatabaseConfig
        from agento.framework.db import get_connection

        try:
            provider = AgentProvider(agent_type)
        except ValueError:
            logger.debug("Unknown agent_type %r; skipping.", agent_type)
            return

        try:
            conn = get_connection(DatabaseConfig.from_env_and_json())
        except Exception:
            logger.warning(
                "Could not open DB connection to resolve replacement token for %s",
                agent_type, exc_info=True,
            )
            return

        try:
            try:
                replacement = TokenResolver().resolve(conn, provider)
            except RuntimeError as exc:
                logger.warning(
                    "No healthy %s token available to replace errored credentials: %s",
                    agent_type, exc,
                )
                return
        finally:
            conn.close()

        if replacement.credentials is None:
            logger.warning(
                "Replacement %s token id=%d has no credentials payload; skipping.",
                agent_type, replacement.id,
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
                writer.write_credentials(target, replacement.credentials)
                updated += 1
                logger.info(
                    "Replaced errored %s credentials in build dir %s "
                    "with token id=%d",
                    agent_type, target, replacement.id,
                )
            except Exception:
                logger.warning(
                    "Failed to replace errored %s credentials in build dir: %s",
                    agent_type, target, exc_info=True,
                )

        if updated:
            logger.info(
                "Replaced %s credentials with token id=%d across %d build dir(s).",
                agent_type, replacement.id, updated,
            )
