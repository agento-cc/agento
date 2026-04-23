"""Event data classes — mutable payloads for the event-observer system."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .job_models import Job

# --- Consumer lifecycle events ---


@dataclass
class ConsumerStartedEvent:
    """Dispatched when the consumer main loop begins."""


@dataclass
class ConsumerStoppingEvent:
    """Dispatched when the consumer begins graceful shutdown."""


# --- Job lifecycle events ---


@dataclass
class JobClaimedEvent:
    """Dispatched after a job is dequeued and claimed (status → RUNNING)."""

    job: Job


@dataclass
class JobSucceededEvent:
    """Dispatched after a job completes successfully (status → SUCCESS)."""

    job: Job
    summary: str | None = None
    agent_type: str | None = None
    model: str | None = None
    elapsed_ms: int = 0


@dataclass
class JobFailedEvent:
    """Dispatched on any job failure (before retry/dead decision)."""

    job: Job
    error: Exception
    elapsed_ms: int = 0


@dataclass
class JobRetryingEvent:
    """Dispatched when a failed job is scheduled for retry (status → TODO)."""

    job: Job
    error: Exception
    delay_seconds: int = 0
    elapsed_ms: int = 0


@dataclass
class JobDeadEvent:
    """Dispatched when a failed job exhausts retries (status → DEAD)."""

    job: Job
    error: Exception
    elapsed_ms: int = 0


@dataclass
class JobPausedEvent:
    """Dispatched after a job is paused (status → PAUSED)."""

    job: Job


@dataclass
class JobResumedEvent:
    """Dispatched after a paused job is re-queued (status → TODO)."""

    job: Job


@dataclass
class JobPublishedEvent:
    """Dispatched after a new job is inserted into the queue."""

    type: str  # AgentType value
    source: str
    reference_id: str | None = None
    idempotency_key: str = ""
    agent_view_id: int | None = None
    priority: int = 50


# --- Worker pool lifecycle events (Phase 9.5) ---


@dataclass
class WorkerStartedEvent:
    """Dispatched when a worker slot begins processing a job."""

    worker_slot: str
    job_id: int


@dataclass
class WorkerStoppedEvent:
    """Dispatched when a worker slot finishes processing a job."""

    worker_slot: str
    job_id: int
    elapsed_ms: int = 0


@dataclass
class AgentViewRunStartedEvent:
    """Dispatched before agent CLI execution for a job with agent_view context."""

    job: Job
    agent_view_id: int | None = None
    provider: str | None = None
    model: str | None = None
    priority: int = 50
    artifacts_dir: str = ""


@dataclass
class AgentViewRunFinishedEvent:
    """Dispatched after agent CLI execution completes (success or failure)."""

    job: Job
    agent_view_id: int | None = None
    provider: str | None = None
    model: str | None = None
    elapsed_ms: int = 0
    success: bool = True


# --- Module lifecycle events ---


@dataclass
class ModuleLoadedEvent:
    """Dispatched after a module's capabilities are registered."""

    name: str
    path: Path


@dataclass
class ModuleRegisterEvent:
    """Dispatched when a module is first loaded (before capability registration)."""

    name: str
    path: Path
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleReadyEvent:
    """Dispatched after all modules are loaded (safe to query registries)."""

    name: str
    path: Path


@dataclass
class ModuleShutdownEvent:
    """Dispatched during graceful shutdown (reverse dependency order)."""

    name: str
    path: Path


# --- Config & setup lifecycle events ---


@dataclass
class ConfigSavedEvent:
    """Dispatched after a config value is set via CLI."""

    path: str
    encrypted: bool = False


@dataclass
class SetupBeforeEvent:
    """Dispatched before setup:upgrade begins work."""

    dry_run: bool = False


@dataclass
class SetupCompleteEvent:
    """Dispatched after setup:upgrade finishes all work."""

    result: Any = None  # SetupResult (avoid circular import with setup.py)
    dry_run: bool = False


@dataclass
class MigrationAppliedEvent:
    """Dispatched after a single SQL migration is applied."""

    version: str
    module: str
    path: Path


@dataclass
class DataPatchAppliedEvent:
    """Dispatched after a data patch is applied."""

    name: str
    module: str


@dataclass
class CrontabInstalledEvent:
    """Dispatched after crontab is updated by setup:upgrade."""

    job_count: int = 0


# --- Routing events ---


@dataclass
class RoutingResolvedEvent:
    """Dispatched after routing successfully resolves to an agent_view."""

    context: Any  # RoutingContext (avoid circular import with router.py)
    agent_view_id: int = 0
    matched_router: str = ""
    reason: str = ""
    candidate_count: int = 0


@dataclass
class RoutingAmbiguousEvent:
    """Dispatched when multiple routers match (first still wins)."""

    context: Any  # RoutingContext
    agent_view_id: int = 0
    matched_router: str = ""
    all_routers: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class RoutingFailedEvent:
    """Dispatched when no router matches the inbound identity."""

    context: Any  # RoutingContext


# --- Workspace build events ---


@dataclass
class WorkspaceBuildStartedEvent:
    """Dispatched when a workspace build begins (status → building)."""

    agent_view_id: int
    build_id: int


@dataclass
class WorkspaceBuildCompletedEvent:
    """Dispatched after a workspace build completes successfully (status → ready)."""

    agent_view_id: int
    build_id: int
    build_dir: str
    checksum: str
    skipped: bool = False


@dataclass
class WorkspaceBuildFailedEvent:
    """Dispatched when a workspace build fails (status → failed)."""

    agent_view_id: int
    build_id: int
    error: str = ""


# --- Skill events ---


@dataclass
class SkillSyncCompletedEvent:
    """Dispatched after skill:sync finishes scanning disk and updating DB."""

    skills_dir: str
    new: int = 0
    updated: int = 0
    unchanged: int = 0


# --- Token events ---


@dataclass
class TokenRegisteredEvent:
    """Dispatched after ``token:register`` upserts an oauth_token row."""

    agent_type: str
    token_id: int
    label: str
    credentials: dict[str, Any]


@dataclass
class TokenRefreshedEvent:
    """Dispatched after ``token:refresh`` re-authenticates and updates oauth_token."""

    agent_type: str
    token_id: int
    label: str
    credentials: dict[str, Any]


@dataclass
class TokenAuthFailedEvent:
    """Dispatched when a runtime auth failure flips a token to ``status='error'``."""

    agent_type: str
    token_id: int
    error_msg: str
    job_id: int | None = None
