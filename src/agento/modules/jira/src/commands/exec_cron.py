"""CLI command: exec:cron — Execute a recurring Jira task."""
from __future__ import annotations

import argparse


class ExecCronCommand:
    @property
    def name(self) -> str:
        return "exec:cron"

    @property
    def help(self) -> str:
        return "Execute a recurring Jira task"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("issue_key")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.bootstrap import bootstrap
        from agento.framework.channels.registry import get_channel
        from agento.framework.cli.runtime import _make_runner
        from agento.framework.job_models import AgentType
        from agento.framework.log import get_logger
        from agento.framework.workflows import get_workflow_class

        bootstrap()
        logger = get_logger("exec-jira-cron-task", "/app/logs/exec-jira-cron-task.log", stderr=False)
        channel = get_channel("jira")
        runner = _make_runner(logger)
        workflow = get_workflow_class(AgentType.CRON)(runner, logger)
        workflow.execute(channel, args.issue_key)
