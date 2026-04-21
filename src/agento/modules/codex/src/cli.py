"""CliInvoker for the Codex CLI (interactive + headless commands)."""
from __future__ import annotations


class CodexCliInvoker:
    def interactive_command(self) -> list[str]:
        return ["codex"]

    def headless_command(
        self, prompt: str, *, model: str | None = None,
    ) -> list[str]:
        cmd = [
            "codex", "exec", prompt,
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]
        if model:
            cmd.extend(["--model", model])
        return cmd
