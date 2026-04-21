"""CliInvoker for the Claude Code CLI (interactive + headless commands)."""
from __future__ import annotations


class ClaudeCliInvoker:
    def interactive_command(self) -> list[str]:
        return ["claude"]

    def headless_command(
        self, prompt: str, *, model: str | None = None,
    ) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd
