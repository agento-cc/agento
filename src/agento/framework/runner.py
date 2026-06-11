from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class McpServerStatus:
    """One MCP server entry from a CLI's session-init self-report."""

    name: str
    status: str


@dataclass(frozen=True)
class McpInitReport:
    """A provider's CLI self-report of the MCP servers visible at session start.

    Generic by design — the framework knows about "MCP server init", not about
    any specific server. Consumers (e.g. app_monitor) pick the server they care
    about out of ``servers``. An empty ``servers`` tuple is a *valid* report
    meaning "the CLI started and saw no MCP servers" — distinct from a missing
    report (``RunResult.mcp_init is None``), which means the provider exposed no
    init signal at all. No ``raw`` field: raw CLI events can carry prompts, tool
    arguments, and customer data; ``(name, status)`` tuples suffice for telemetry.
    """

    servers: tuple[McpServerStatus, ...]


@dataclass
class RunResult:
    """Provider-agnostic result of a single LLM CLI run."""

    raw_output: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    subtype: str | None = None
    agent_type: str | None = None
    model: str | None = None
    prompt: str | None = None
    mcp_init: McpInitReport | None = None

    @property
    def stats_line(self) -> str:
        return (
            f"turns={self.num_turns or '?'} "
            f"in={self.input_tokens or '?'} "
            f"out={self.output_tokens or '?'} "
            f"cost_usd={self.cost_usd or '?'} "
            f"duration_ms={self.duration_ms or '?'}"
        )


@runtime_checkable
class Runner(Protocol):
    """Protocol that any LLM runner must satisfy."""

    def run(self, prompt: str, *, model: str | None = None) -> RunResult: ...

    def resume(self, session_id: str, *, model: str | None = None) -> RunResult: ...

    def build_command(self, prompt: str, *, model: str | None = None) -> list[str]: ...
