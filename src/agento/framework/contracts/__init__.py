"""Public contracts for Agento modules.

Module authors should import from here — these are the stable interfaces.
"""

from __future__ import annotations

from ..channels.base import Channel, DiscoverableChannel, PromptFragments, Publisher, WorkItem
from ..commands import Command
from ..data_patch import DataPatch
from ..encryptor import Encryptor
from ..event_manager import EventManager, Observer, ObserverEntry
from ..events import (
    ConfigSavedEvent,
    ConsumerStartedEvent,
    ConsumerStoppingEvent,
    CrontabInstalledEvent,
    DataPatchAppliedEvent,
    JobClaimedEvent,
    JobDeadEvent,
    JobFailedEvent,
    JobPublishedEvent,
    JobRetryingEvent,
    JobSucceededEvent,
    MigrationAppliedEvent,
    ModuleLoadedEvent,
    ModuleReadyEvent,
    ModuleRegisterEvent,
    ModuleShutdownEvent,
    RoutingAmbiguousEvent,
    RoutingFailedEvent,
    RoutingResolvedEvent,
    SetupBeforeEvent,
    SetupCompleteEvent,
)
from ..ingress_identity import IngressIdentity
from ..job_models import AgentType, Job, JobStatus
from ..router import Router, RoutingCandidate, RoutingContext, RoutingDecision, RoutingResult
from ..runner import Runner, RunResult
from ..workflows.base import JobContext, Workflow

__all__ = [
    "AgentType",
    "Channel",
    "Command",
    "ConfigSavedEvent",
    "ConsumerStartedEvent",
    "ConsumerStoppingEvent",
    "CrontabInstalledEvent",
    "DataPatch",
    "DataPatchAppliedEvent",
    "DiscoverableChannel",
    "Encryptor",
    "EventManager",
    "IngressIdentity",
    "Job",
    "JobClaimedEvent",
    "JobContext",
    "JobDeadEvent",
    "JobFailedEvent",
    "JobPublishedEvent",
    "JobRetryingEvent",
    "JobStatus",
    "JobSucceededEvent",
    "MigrationAppliedEvent",
    "ModuleLoadedEvent",
    "ModuleReadyEvent",
    "ModuleRegisterEvent",
    "ModuleShutdownEvent",
    "Observer",
    "ObserverEntry",
    "PromptFragments",
    "Publisher",
    "Router",
    "RoutingAmbiguousEvent",
    "RoutingCandidate",
    "RoutingContext",
    "RoutingDecision",
    "RoutingFailedEvent",
    "RoutingResolvedEvent",
    "RoutingResult",
    "RunResult",
    "Runner",
    "SetupBeforeEvent",
    "SetupCompleteEvent",
    "WorkItem",
    "Workflow",
]
