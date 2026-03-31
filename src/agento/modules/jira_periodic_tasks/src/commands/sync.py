"""CLI command: jira:periodic:sync — Jira recurring tasks to crontab."""
from __future__ import annotations

import argparse

from agento.modules.jira.src.toolbox_client import ToolboxClient
from agento.modules.jira_periodic_tasks.src.crontab import CrontabManager
from agento.modules.jira_periodic_tasks.src.sync import JiraCronSync


class SyncCommand:
    @property
    def name(self) -> str:
        return "jira:periodic:sync"

    @property
    def help(self) -> str:
        return "Sync Jira recurring tasks to crontab"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.bootstrap import bootstrap, get_module_config
        from agento.framework.cli.runtime import _load_framework_config
        from agento.framework.db import get_connection
        from agento.framework.log import get_logger

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            bootstrap(db_conn=conn)
        finally:
            conn.close()

        jira_config = get_module_config("jira")
        periodic_config = get_module_config("jira_periodic_tasks")
        logger = get_logger("sync-jira-cron", "/app/logs/sync-jira-cron.log", stderr=False)
        toolbox = ToolboxClient(jira_config.toolbox_url)
        crontab = CrontabManager()

        syncer = JiraCronSync(jira_config, periodic_config, toolbox, crontab, logger, db_config=db_config)
        syncer.sync(dry_run=args.dry_run)
