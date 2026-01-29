from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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

    def build_command(self, prompt: str, *, model: str | None = None) -> list[str]: ...
