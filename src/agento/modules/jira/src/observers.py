"""Observers for the jira module."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


def _resolve_account_id(toolbox_url, agent_view_id=None):
    """Call /myself via toolbox and return accountId or None."""
    from .toolbox_client import ToolboxClient

    toolbox = ToolboxClient(toolbox_url)
    try:
        myself = toolbox.jira_request(
            "GET", "/rest/api/3/myself",
            agent_view_id=agent_view_id,
        )
    finally:
        toolbox.close()
    return myself.get("accountId", "") or None


class ResolveAccountIdObserver:
    """Auto-resolve jira_assignee_account_id via /myself for agent_views only."""

    def execute(self, event) -> None:
        if event.name != "jira":
            return

        from agento.framework.bootstrap import get_module_config

        config = get_module_config("jira")
        if not config or not hasattr(config, "jira_assignee_account_id"):
            return

        toolbox_url = config.toolbox_url
        if not toolbox_url:
            return

        self._resolve_agent_views(toolbox_url)

    def _resolve_agent_views(self, toolbox_url):
        try:
            from agento.framework.database_config import DatabaseConfig
            from agento.framework.db import get_connection
            from agento.framework.workspace import get_active_agent_views

            conn = get_connection(DatabaseConfig.from_env())
            try:
                for av in get_active_agent_views(conn):
                    self._resolve_single_agent_view(conn, av, toolbox_url)
            finally:
                conn.close()

        except httpx.ConnectError as exc:
            logger.info("jira: toolbox not reachable yet, skipping agent_view account IDs (%s)", exc)
        except Exception:
            logger.warning("jira: failed to resolve agent_view account IDs (non-fatal)")

    def _resolve_single_agent_view(self, conn, av, toolbox_url):
        from agento.framework.scoped_config import (
            Scope,
            ScopedConfig,
            load_scoped_db_overrides,
            scoped_config_set,
        )

        # Check if this agent_view has its own Jira credentials at agent_view scope
        av_overrides = load_scoped_db_overrides(conn, Scope.AGENT_VIEW, av.id)
        has_own_user = "jira/jira_user" in av_overrides
        has_own_account_id = "jira/jira_assignee_account_id" in av_overrides
        if not has_own_user:
            logger.debug("jira: agent_view %s has no own jira_user, skipping", av.code)
            return
        if has_own_account_id:
            existing = av_overrides["jira/jira_assignee_account_id"][0]
            if existing:
                logger.debug("jira: agent_view %s already has account_id, skipping", av.code)
                return

        # Verify credentials are actually set (non-empty)
        sc = ScopedConfig(conn, scope=Scope.AGENT_VIEW, scope_id=av.id)
        scoped_user = sc.get_value("jira/jira_user")
        scoped_token = sc.get_value("jira/jira_token")
        if not scoped_user or not scoped_token:
            return

        try:
            account_id = _resolve_account_id(toolbox_url, agent_view_id=av.id)
            if not account_id:
                logger.warning("jira: /myself missing accountId for agent_view %s", av.code)
                return

            scoped_config_set(
                conn, "jira/jira_assignee_account_id", account_id,
                scope=Scope.AGENT_VIEW, scope_id=av.id,
            )
            conn.commit()
            logger.info("jira: auto-resolved account ID for agent_view %s: %s", av.code, account_id)

        except httpx.ConnectError as exc:
            logger.info(
                "jira: toolbox not reachable yet, skipping account ID for agent_view %s (%s)",
                av.code, exc,
            )
        except Exception:
            logger.warning(
                "jira: failed to auto-resolve account ID for agent_view %s (non-fatal)",
                av.code, exc_info=True,
            )
