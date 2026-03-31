"""CLI command: publish — Publish Jira jobs to the queue."""
from __future__ import annotations

import argparse
import dataclasses
import sys

from agento.framework.log import get_logger
from agento.modules.jira.src.channel import publish_cron, publish_mentions, publish_todo
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
        db_config, jira_config = _load_configs()
        logger = get_logger("publisher", "/app/logs/publisher.log", stderr=False)

        kind = args.kind
        if kind == "jira-cron":
            if not args.issue_key:
                logger.error("issue_key required for jira-cron")
                sys.exit(1)
            publish_cron(db_config, args.issue_key, logger)
        elif kind == "jira-todo":
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
                publish_todo(db_config, issue_key=tasks[0].issue.key, updated=tasks[0].issue.updated, logger=logger, payload=dataclasses.asdict(tasks[0].issue))
        elif kind == "jira-mention":
            count = publish_mentions(jira_config, logger, db_config=db_config)
            logger.info(f"Published {count} mention jobs")
        else:
            logger.error(f"Unknown publish kind: {kind}")
            sys.exit(1)
