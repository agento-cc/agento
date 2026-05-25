"""Observers for the workspace_build module."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from agento.framework.agent_manager.models import AgentProvider, Token, TokenStatus
from agento.framework.config_writer import get_config_writer
from agento.framework.database_config import DatabaseConfig
from agento.framework.db import get_connection
from agento.framework.workspace_paths import BUILD_DIR

logger = logging.getLogger(__name__)

_EPOCH = datetime(2000, 1, 1)


def _token_from_event(event) -> Token:
    """Construct a minimal Token from a token event (register/refresh).

    Events carry ``agent_type``, ``token_id``, ``label``, ``credentials``,
    and (since the fix) ``type``. Falls back to ``"oauth"`` for events that
    pre-date the field.
    """
    try:
        provider = AgentProvider(event.agent_type)
    except ValueError:
        logger.error(
            "Unrecognised agent_type %r in token event; falling back to CLAUDE. "
            "This usually means a misconfigured event dispatch — refreshed "
            "credentials may end up in the wrong provider's build dir.",
            event.agent_type,
        )
        provider = AgentProvider.CLAUDE
    return Token(
        id=getattr(event, "token_id", 0),
        agent_type=provider,
        type=getattr(event, "type", None) or "oauth",
        label=getattr(event, "label", ""),
        credentials=getattr(event, "credentials", {}),
        model=None,
        token_limit=0,
        enabled=True,
        status=TokenStatus.OK,
        priority=0,
        error_msg=None,
        expires_at=None,
        used_at=None,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    )


class BuildFreshnessCheckObserver:
    """Rebuild the workspace if the resolved scoped config drifted from the
    on-disk build. Fires on ``workspace_build_check_before`` dispatched by
    the consumer at job-claim time.

    Idempotent — ``execute_build`` skips when the checksum matches and the
    build_dir is intact. Rebuilds otherwise (provider switch, model change,
    skill changes, instructions, mcp/servers, persistent-path contract drift
    after an agento-core upgrade).

    Captures exceptions on the event so the consumer can re-raise them
    (EventManager.dispatch swallows raised exceptions, but a silent rebuild
    failure would let the job run with a stale build — the exact bug this
    observer was introduced to prevent)."""

    def execute(self, event) -> None:
        agent_view_id = getattr(event, "agent_view_id", None)
        if agent_view_id is None:
            return

        from .builder import execute_build

        try:
            conn = get_connection(DatabaseConfig.from_env())
        except Exception as exc:
            event.error = exc
            logger.exception(
                "BuildFreshnessCheckObserver: could not open DB connection",
            )
            return

        try:
            execute_build(conn, agent_view_id)
        except Exception as exc:
            event.error = exc
            logger.exception(
                "BuildFreshnessCheckObserver: execute_build failed for "
                "agent_view_id=%s", agent_view_id,
            )
        finally:
            conn.close()


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

        token = _token_from_event(event)

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
                writer.write_credentials(target, token)
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
            conn = get_connection(DatabaseConfig.from_env())
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
                writer.write_credentials(target, replacement)
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
