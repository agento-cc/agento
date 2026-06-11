"""TranscriptReader protocol and registry — agent-agnostic transcript parsing.

Each agent module (claude, codex, etc.) owns the format of its own session
transcript: file location, JSON shape, what counts as a "tool use". Framework
defines the protocol and registry; modules register implementations via
``di.json`` under ``"transcript_readers"``.

Consumers (such as ``app_monitor.McpHealthTelemetryObserver``) look up the reader
by provider — they must never read provider-specific files directly.

Readers return a :class:`ParseSummary` so callers can distinguish "agent did
nothing" from "parser saw a file full of records it didn't recognize"
(silent format drift). ``iter_tool_uses`` remains as a convenience wrapper
for the common case where only the tool-use stream matters.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .agent_manager.models import AgentProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolUse:
    """Single tool invocation observed in an agent session."""

    name: str
    tool_use_id: str


@dataclass(frozen=True)
class ParseSummary:
    """Result of parsing a session transcript.

    ``total_json_lines`` is the number of lines in the file whose JSON parses
    successfully (regardless of shape). ``recognized_records`` counts lines
    whose outer shape matched what the reader expects. A non-zero
    ``total_json_lines`` with zero ``recognized_records`` is the canonical
    signal for "the provider changed its transcript format silently".
    """

    total_json_lines: int
    recognized_records: int
    tool_uses: tuple[ToolUse, ...]


@runtime_checkable
class TranscriptReader(Protocol):
    """Protocol any agent transcript reader must satisfy."""

    def parse(self, session_id: str) -> ParseSummary:
        """Return parse stats + tool uses for ``session_id``.

        Raises:
            FileNotFoundError: when no transcript exists for the session.
        """
        ...

    def iter_tool_uses(self, session_id: str) -> Iterable[ToolUse]:
        """Yield every tool invocation recorded for ``session_id``.

        Default-implemented in concrete readers as ``self.parse(sid).tool_uses``;
        kept for callers that only want the stream.

        Raises:
            FileNotFoundError: when no transcript exists for the session.
        """
        ...


_TRANSCRIPT_READERS: dict[AgentProvider, TranscriptReader] = {}


def register_transcript_reader(provider: AgentProvider, reader: TranscriptReader) -> None:
    """Register a transcript reader for an agent provider."""
    _TRANSCRIPT_READERS[provider] = reader
    logger.debug("Registered transcript reader for provider %s", provider.value)


def get_transcript_reader(provider: AgentProvider | str) -> TranscriptReader | None:
    """Look up the TranscriptReader for a provider.

    Returns ``None`` when no reader is registered (e.g. provider has no
    transcript concept, or its module isn't loaded). Callers decide policy —
    the framework doesn't assume every provider must verify.
    """
    if isinstance(provider, str):
        try:
            provider = AgentProvider(provider)
        except ValueError:
            return None
    return _TRANSCRIPT_READERS.get(provider)


def clear() -> None:
    """Reset registry (for testing)."""
    _TRANSCRIPT_READERS.clear()
