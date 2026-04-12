"""Observers for the jira module."""
from __future__ import annotations

import dataclasses
import logging

logger = logging.getLogger(__name__)


def _resolve_account_id(toolbox_url, auth_user=None, auth_token=None, jira_host=None):
    """Call /myself via toolbox and return accountId or None."""
    from .toolbox_client import ToolboxClient

    toolbox = ToolboxClient(toolbox_url)
    try:
        myself = toolbox.jira_request(
            "GET", "/rest/api/3/myself",
            auth_user=auth_user, auth_token=auth_token,
            jira_host=jira_host,
        )
    finally:
        toolbox.close()
    return myself.get("accountId", "") or None


class ResolveAccountIdObserver:
    """Auto-resolve jira_assignee_account_id via /myself when empty."""

    def execute(self, event) -> None:
        if event.name != "jira":
            return

        from agento.framework.bootstrap import get_module_config, set_module_config

        config = get_module_config("jira")
        if not config or not hasattr(config, "jira_assignee_account_id"):
            return

        toolbox_url = config.toolbox_url
        if not toolbox_url:
            return

        # 1. Resolve at default scope (global config)
        if not config.jira_assignee_account_id:
            self._resolve_default(config, toolbox_url, set_module_config)

        # 2. Resolve at agent_view scopes
        self._resolve_agent_views(toolbox_url)

    def _resolve_default(self, config, toolbox_url, set_module_config):
        try:
            from agento.framework.core_config import config_set
            from agento.framework.database_config import DatabaseConfig
            from agento.framework.db import get_connection

            account_id = _resolve_account_id(toolbox_url)
            if not account_id:
                logger.warning("jira: /myself response missing accountId")
                return

            conn = get_connection(DatabaseConfig.from_env())
            try:
                config_set(conn, "jira/jira_assignee_account_id", account_id)
                conn.commit()
            finally:
                conn.close()

            updated = dataclasses.replace(config, jira_assignee_account_id=account_id)
            set_module_config("jira", updated)
            logger.info("jira: auto-resolved default account ID: %s", account_id)

        except Exception:
            logger.warning("jira: failed to auto-resolve default account ID (non-fatal)", exc_info=True)

    def _resolve_agent_views(self, toolbox_url):
        try:
            from agento.framework.database_config import DatabaseConfig
            from agento.framework.db import get_connection
            from agento.framework.scoped_config import ScopedConfig, scoped_config_set
            from agento.framework.workspace import get_active_agent_views

            conn = get_connection(DatabaseConfig.from_env())
            try:
                for av in get_active_agent_views(conn):
                    self._resolve_single_agent_view(conn, av, toolbox_url)
            finally:
                conn.close()

        except Exception:
            logger.warning("jira: failed to resolve agent_view account IDs (non-fatal)", exc_info=True)

    def _resolve_single_agent_view(self, conn, av, toolbox_url):
        from agento.framework.encryptor import get_encryptor
        from agento.framework.scoped_config import Scope, ScopedConfig, scoped_config_set

        sc = ScopedConfig(conn, scope=Scope.AGENT_VIEW, scope_id=av.id)

        # Already resolved at this scope?
        account_id = sc.get_value("jira/jira_assignee_account_id")
        if account_id:
            return

        # Need scoped credentials to call /myself for this agent_view
        scoped_user = sc.get_value("jira/jira_user")
        scoped_token = sc.get_value("jira/jira_token")
        scoped_host = sc.get_value("jira/jira_host")
        if not scoped_user or not scoped_token:
            return

        try:
            account_id = _resolve_account_id(
                toolbox_url, auth_user=scoped_user, auth_token=scoped_token,
                jira_host=scoped_host,
            )
            if not account_id:
                logger.warning("jira: /myself missing accountId for agent_view %s", av.code)
                return

            scoped_config_set(
                conn, "jira/jira_assignee_account_id", account_id,
                scope=Scope.AGENT_VIEW, scope_id=av.id,
            )
            conn.commit()
            logger.info("jira: auto-resolved account ID for agent_view %s: %s", av.code, account_id)

        except Exception:
            logger.warning(
                "jira: failed to auto-resolve account ID for agent_view %s (non-fatal)",
                av.code, exc_info=True,
            )
