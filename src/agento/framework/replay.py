"""Reconstruct executable CLI commands from completed jobs."""
from __future__ import annotations

import shlex
from dataclasses import dataclass

from .agent_manager.models import AgentProvider
from .database_config import DatabaseConfig
from .job_models import Job
from .runner_factory import create_runner


@dataclass
class ReplayCommand:
    """A reconstructed CLI command for a job."""
    args: list[str]
    agent_type: str
    model: str | None
    prompt: str
    job: Job

    @property
    def shell_command(self) -> str:
        """Return a shell-safe command string."""
        return " ".join(shlex.quote(a) for a in self.args)


def _resolve_agent_type(job: Job, agent_type_override: str | None) -> str:
    """Resolve agent type string from override or job record."""
    if agent_type_override:
        try:
            AgentProvider(agent_type_override)
        except ValueError as exc:
            raise ValueError(f"Unknown agent type: {agent_type_override}") from exc
        return agent_type_override
    if job.agent_type:
        try:
            AgentProvider(job.agent_type)
        except ValueError as exc:
            raise ValueError(f"Unknown agent type: {job.agent_type}") from exc
        return job.agent_type
    raise ValueError(
        f"Job {job.id} has no agent_type recorded. "
        f"Use --oauth_token to specify which agent to use."
    )


def build_replay_command(
    job: Job,
    *,
    agent_type_override: str | None = None,
    model_override: str | None = None,
) -> ReplayCommand:
    """Build the CLI command that would reproduce a job's execution.

    Args:
        agent_type_override: Agent short name ("claude" or "codex").
        model_override: Model name override.

    Raises:
        ValueError: If job has no stored prompt or agent_type cannot be resolved.
    """
    if not job.prompt:
        raise ValueError(
            f"Job {job.id} has no stored prompt. "
            f"Only jobs executed after migration 008 have prompts."
        )

    agent_type = _resolve_agent_type(job, agent_type_override)
    model = model_override or job.model
    prompt = job.prompt

    provider = AgentProvider(agent_type)
    runner = create_runner(provider, dry_run=True)
    cmd = runner.build_command(prompt, model=model)

    return ReplayCommand(
        args=cmd,
        agent_type=agent_type,
        model=model,
        prompt=prompt,
        job=job,
    )


def fetch_job_for_replay(job_id: int, config: DatabaseConfig) -> Job:
    """Fetch a job by ID for replay purposes.

    Raises:
        ValueError: If job not found.
    """
    from .db import get_connection

    conn = get_connection(config)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM job WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Job {job_id} not found.")
            return Job.from_row(row)
    finally:
        conn.close()
