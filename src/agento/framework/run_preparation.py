"""Shared pre-spawn pipeline for jobs (consumer) and interactive runs (``agento run``).

Encapsulates the freshness check + per-run artifacts dir + build copy that
both paths must do identically: select the right token pool elsewhere, but
materialize the workspace the same way so a manual ``agento run`` lands in
the same dir layout the consumer prepares for a real job.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .artifacts_dir import (
    build_artifacts_dir,
    copy_build_to_artifacts_dir,
    get_current_build_dir,
    prepare_artifacts_dir,
)
from .event_manager import get_event_manager
from .events import WorkspaceBuildCheckEvent

if TYPE_CHECKING:
    from .agent_view_runtime import AgentViewRuntime


def materialize_run_workspace(
    runtime: AgentViewRuntime,
    *,
    run_id: int | str,
    agent_config_svc=None,
    toolbox_url: str = "http://toolbox:3001",
    em=None,
) -> tuple[Path | None, Path | None]:
    """Prepare ``(home_dir, working_dir)`` for one run.

    Mirrors ``consumer._run_job`` lines 453-486 byte-for-byte semantically:
    dispatches ``workspace_build_check_before`` (re-raising ``event.error`` —
    ``EventManager.dispatch`` swallows observer exceptions, so the observer
    surfaces failures via ``event.error``), creates the per-run artifacts
    dir, and copies the current build into it. Falls back to a fresh
    ``ConfigWriter.prepare_workspace`` when no build exists yet.

    ``run_id`` is the job id (``int``) for the consumer or any stable string
    (e.g. ``"run"``) for ``agento run``. Pass ``int`` job ids to get per-job
    ``inject_runtime_params``; ``str`` ids skip injection (interactive run
    uses the build's baked ``.mcp.json``).

    Returns ``(None, None)`` when ``runtime`` carries no agent_view/workspace
    (blank jobs), mirroring the consumer guard.
    """
    if runtime.agent_view is None or runtime.workspace is None:
        return None, None

    event_manager = em or get_event_manager()

    check_event = WorkspaceBuildCheckEvent(agent_view_id=runtime.agent_view.id)
    event_manager.dispatch("workspace_build_check_before", check_event)
    if check_event.error is not None:
        raise check_event.error

    artifacts_dir = build_artifacts_dir(
        runtime.workspace.code, runtime.agent_view.code, run_id,
    )
    prepare_artifacts_dir(artifacts_dir)

    current_build = get_current_build_dir(
        runtime.workspace.code, runtime.agent_view.code,
    )
    if current_build is not None:
        # int job ids drive per-job .mcp.json injection; str run ids skip it.
        inject_id = run_id if isinstance(run_id, int) else None
        copy_build_to_artifacts_dir(
            current_build, artifacts_dir,
            job_id=inject_id,
            provider=runtime.provider,
        )
    elif runtime.provider:
        from .config_writer import get_agent_config, get_config_writer
        agent_config = get_agent_config(agent_config_svc) if agent_config_svc else {}
        writer = get_config_writer(runtime.provider)
        writer.prepare_workspace(
            artifacts_dir, agent_config,
            agent_view_id=runtime.agent_view.id,
            toolbox_url=toolbox_url,
        )

    return current_build, artifacts_dir
