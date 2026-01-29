from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PromptFragments:
    """Prompt instruction blocks that a channel provides.

    Each field is a Polish-language instruction string, or None if the channel
    does not support that capability. Workflows compose these into full prompts.
    """

    read_context: str
    respond: str
    transition_start: str | None = None
    transition_done: str | None = None
    assign_back: str | None = None
    ask_and_handback: str | None = None
    extra: str | None = None


@dataclass
class WorkItem:
    """Channel-agnostic representation of a discoverable work item."""

    reference_id: str
    title: str
    priority: int  # 1=critical, 4=low
    reason: str
    source_tag: str
    updated: str | None = None
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Channel(Protocol):
    """Protocol that every communication channel must satisfy."""

    @property
    def name(self) -> str: ...

    def get_prompt_fragments(self, reference_id: str) -> PromptFragments: ...

    def get_followup_fragments(
        self, reference_id: str, instructions: str
    ) -> PromptFragments: ...


@runtime_checkable
class DiscoverableChannel(Protocol):
    """Channel that can discover pending work items."""

    def discover_work(
        self, config: object, logger: logging.Logger
    ) -> list[WorkItem]: ...


@runtime_checkable
class Publisher(Protocol):
    """Protocol for publishing jobs to the queue."""

    @property
    def name(self) -> str: ...

    def publish_todo(
        self,
        config: object,
        reference_id: str | None = None,
        **kwargs: object,
    ) -> bool: ...

    def publish_cron(
        self,
        config: object,
        reference_id: str,
        **kwargs: object,
    ) -> bool: ...
