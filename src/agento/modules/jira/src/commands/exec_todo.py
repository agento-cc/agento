"""CLI command: exec:todo — Execute next TODO task (or specific issue)."""
from __future__ import annotations

import argparse


class ExecTodoCommand:
    @property
    def name(self) -> str:
        return "exec:todo"

    @property
    def help(self) -> str:
        return "Execute next TODO task (or specific issue)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("issue_key", nargs="?")

    def execute(self, args: argparse.Namespace) -> None:
        from agento.framework.bootstrap import bootstrap, get_module_config
        from agento.framework.channels.registry import get_channel
        from agento.framework.cli.runtime import _load_framework_config, _make_runner
        from agento.framework.db import get_connection
        from agento.framework.job_models import AgentType, Job
        from agento.framework.log import get_logger
        from agento.framework.workflows import get_workflow_class
        from agento.framework.workflows.base import JobContext

        db_config, _, _ = _load_framework_config()
        conn = get_connection(db_config)
        try:
            bootstrap(db_conn=conn)
        finally:
            conn.close()

        jira_config = get_module_config("jira")
        logger = get_logger("exec-jira-todo-task", "/app/logs/exec-jira-todo-task.log", stderr=False)
        channel = get_channel("jira")
        runner = _make_runner(logger)
        workflow = get_workflow_class(AgentType.TODO)(runner, logger)

        job = Job.stub(type=AgentType.TODO, source="jira", reference_id=args.issue_key or None)
        context = JobContext(config=jira_config, logger=logger, update_reference_id=lambda *a: None)
        workflow.execute_job(channel, job, context)
