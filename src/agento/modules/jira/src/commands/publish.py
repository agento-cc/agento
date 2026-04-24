"""CLI command: publish — Publish Jira jobs to the queue."""
from __future__ import annotations

import argparse
import dataclasses
import sys

from agento.framework.log import get_logger
from agento.modules.jira.src.channel import JiraPublisher, publish_cron
from agento.modules.jira.src.task_list import TaskListBuilder
from agento.modules.jira.src.toolbox_client import ToolboxClient


def _load_configs():
    """Load framework + jira module config via bootstrap."""
    from agento.framework.bootstrap import bootstrap, get_module_config
    from agento.framework.cli.runtime import _load_framework_config
    from agento.framework.db import get_connection

    db_config, _, _ = _load_framework_config()
    conn = get_connection(db_config)
    try:
        bootstrap(db_conn=conn)
    finally:
        conn.close()
    return db_config, get_module_config("jira")


def _get_connection_and_bootstrap():
    """Bootstrap and return (db_config, conn). Caller must close conn."""
    from agento.framework.bootstrap import bootstrap
    from agento.framework.cli.runtime import _load_framework_config
    from agento.framework.db import get_connection

    db_config, _, _ = _load_framework_config()
    conn = get_connection(db_config)
    try:
        bootstrap(db_conn=conn)
    except Exception:
        conn.close()
        raise
    return db_config, conn


_publisher = JiraPublisher()


class PublishCommand:
    @property
    def name(self) -> str:
        return "publish"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Publish a job to the queue"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("kind", choices=["jira-cron", "jira-todo", "jira-mention"])
        parser.add_argument("issue_key", nargs="?")

    def execute(self, args: argparse.Namespace) -> None:
        logger = get_logger("publisher", "/app/logs/publisher.log", stderr=False)
        kind = args.kind

        if kind == "jira-cron":
            self._execute_cron(args, logger)
            return

        # For todo (no issue_key) and mention: iterate active agent_views
        db_config, conn = _get_connection_and_bootstrap()
        try:
            self._execute_per_agent_view(kind, args, db_config, conn, logger)
        finally:
            conn.close()

    def _execute_cron(self, args, logger):
        """Cron: specific issue_key. Use single enabled agent_view if only one, else routing."""
        if not args.issue_key:
            logger.error("issue_key required for jira-cron")
            sys.exit(1)

        db_config, conn = _get_connection_and_bootstrap()
        try:
            agent_view_id, priority = self._resolve_single_agent_view(conn, logger)
            if agent_view_id is not None:
                _publisher.publish_cron(
                    db_config, args.issue_key, logger,
                    agent_view_id=agent_view_id, priority=priority,
                )
            else:
                # Multiple or zero enabled agent_views — fall back to routing
                publish_cron(db_config, args.issue_key, logger)
        finally:
            conn.close()

    def _execute_per_agent_view(self, kind, args, db_config, conn, logger):
        """Iterate active agent_views, resolve scoped config for each, publish."""
        from agento.framework.agent_view_runtime import resolve_publish_priority
        from agento.framework.bootstrap import get_module_config
        from agento.framework.scoped_config import Scope
        from agento.framework.scoped_config import get_module_config as get_scoped_config
        from agento.framework.workspace import get_active_agent_views

        agent_views = get_active_agent_views(conn)

        if not agent_views:
            # Fallback: no agent_views configured, use global config (backward compat)
            logger.debug("No active agent_views, falling back to global config")
            jira_config = get_module_config("jira")
            self._execute_global(kind, args, db_config, jira_config, logger)
            return

        for av in agent_views:
            jira_config = get_scoped_config(conn, "jira", scope=Scope.AGENT_VIEW, scope_id=av.id)
            if jira_config is None:
                logger.warning("Could not resolve jira config for agent_view %s, skipping", av.code)
                continue
            if not jira_config.enabled:
                logger.debug("Jira disabled for agent_view %s, skipping", av.code)
                continue

            priority = resolve_publish_priority(conn, av.id)
            logger.info("Publishing %s for agent_view %s (id=%d)", kind, av.code, av.id)

            try:
                if kind == "jira-todo":
                    self._publish_todo_for_agent_view(args, db_config, jira_config, av.id, priority, logger)
                elif kind == "jira-mention":
                    count = _publisher.publish_mentions(
                        jira_config, logger, db_config=db_config,
                        agent_view_id=av.id, priority=priority,
                    )
                    logger.info("Published %d mention jobs for agent_view %s", count, av.code)
            except Exception:
                logger.exception(
                    "Failed to publish %s for agent_view %s (id=%d), continuing",
                    kind, av.code, av.id,
                )

    def _publish_todo_for_agent_view(self, args, db_config, jira_config, agent_view_id, priority, logger):
        """Publish todo for a specific agent_view."""
        if args.issue_key:
            _publisher.publish_todo(
                db_config, args.issue_key, logger=logger,
                agent_view_id=agent_view_id, priority=priority,
            )
        else:
            ai_user = jira_config.jira_assignee or jira_config.user
            if not ai_user:
                logger.warning("jira_assignee/user not set for this agent_view, skipping")
                return
            toolbox = ToolboxClient(jira_config.toolbox_url)
            builder = TaskListBuilder(toolbox, jira_config, ai_user, logger, agent_view_id=agent_view_id)
            tasks = builder.get_todo_tasks()
            if not tasks:
                logger.debug("No TODO tasks, skipping")
                return
            _publisher.publish_todo(
                db_config, reference_id=tasks[0].issue.key,
                updated=tasks[0].issue.updated, logger=logger,
                agent_view_id=agent_view_id, priority=priority,
            )

    def _execute_global(self, kind, args, db_config, jira_config, logger):
        """Fallback: execute with global config (no agent_views configured)."""
        from agento.modules.jira.src.channel import publish_mentions, publish_todo

        if kind == "jira-todo":
            if args.issue_key:
                publish_todo(db_config, args.issue_key, logger=logger)
            else:
                ai_user = jira_config.jira_assignee or jira_config.user
                if not ai_user:
                    logger.error("config.jira_assignee/user not set")
                    sys.exit(1)
                toolbox = ToolboxClient(jira_config.toolbox_url)
                builder = TaskListBuilder(toolbox, jira_config, ai_user, logger)
                tasks = builder.get_todo_tasks()
                if not tasks:
                    logger.debug("No TODO tasks in Jira, skipping publish")
                    return
                publish_todo(
                    db_config, issue_key=tasks[0].issue.key,
                    updated=tasks[0].issue.updated, logger=logger,
                    payload=dataclasses.asdict(tasks[0].issue),
                )
        elif kind == "jira-mention":
            count = publish_mentions(jira_config, logger, db_config=db_config)
            logger.info("Published %d mention jobs", count)

    def _resolve_single_agent_view(self, conn, logger):
        """If exactly 1 jira-enabled agent_view exists, return (id, priority). Else (None, 50)."""
        from agento.framework.agent_view_runtime import resolve_publish_priority
        from agento.framework.scoped_config import Scope
        from agento.framework.scoped_config import get_module_config as get_scoped_config
        from agento.framework.workspace import get_active_agent_views

        agent_views = get_active_agent_views(conn)
        enabled = []
        for av in agent_views:
            jira_config = get_scoped_config(conn, "jira", scope=Scope.AGENT_VIEW, scope_id=av.id)
            if jira_config is not None and jira_config.enabled:
                enabled.append(av)

        if len(enabled) == 1:
            av = enabled[0]
            priority = resolve_publish_priority(conn, av.id)
            return av.id, priority

        return None, 50
