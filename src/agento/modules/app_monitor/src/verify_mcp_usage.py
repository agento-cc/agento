"""Pure verifier — translate observed tool-use stream into a Verdict.

Channel-agnostic invariant: a job that claims success must have made at least
one ``mcp__toolbox__*`` tool call. Zero calls indicates the agent never
contacted the toolbox (broken MCP registration, no work attempted, etc.) and
the apparent ``rc=0`` is a "ghost success" of the kind that caused incidents
3292 and 3368.
"""
from __future__ import annotations

from collections.abc import Iterable

from agento.framework.events import Verdict, VerifyReason
from agento.framework.transcript_reader import ToolUse

from .constants import MCP_TOOLBOX_TOOL_PREFIX


def verify(tool_uses: Iterable[ToolUse]) -> Verdict | None:
    """Return ``None`` on pass, populated ``Verdict`` on veto."""
    for t in tool_uses:
        if t.name.startswith(MCP_TOOLBOX_TOOL_PREFIX):
            return None
    return Verdict(
        retryable=True,
        reason=VerifyReason.NO_MCP_CALLS,
        fresh_start=True,
        detail=f"agent made zero {MCP_TOOLBOX_TOOL_PREFIX}* tool calls in this session",
    )
