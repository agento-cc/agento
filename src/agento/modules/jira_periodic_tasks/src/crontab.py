from __future__ import annotations

import subprocess
from dataclasses import dataclass

MARKER_BEGIN = "# JIRA-SYNC:BEGIN - Auto-generated. Do not edit manually."
MARKER_END = "# JIRA-SYNC:END"

ENV_FILE = "/opt/cron-agent/env"
ENVLOAD = f"set -a; source {ENV_FILE}; set +a"
EXEC_COMMAND_TEMPLATE = f"{ENVLOAD}; cd /workspace && /opt/cron-agent/run.sh publish jira-cron {{issue_key}} >/dev/null 2>&1"


@dataclass
class CronEntry:
    issue_key: str
    summary: str
    frequency_label: str
    cron_expression: str

    @property
    def command(self) -> str:
        return EXEC_COMMAND_TEMPLATE.format(issue_key=self.issue_key)

    def to_crontab_lines(self) -> str:
        return f"# {self.issue_key}: {self.summary} ({self.frequency_label})\n{self.cron_expression} {self.command}"


class CrontabManager:

    def get_current(self) -> str:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout

    def extract_unmanaged(self, crontab: str) -> str:
        lines = crontab.splitlines()
        out: list[str] = []
        skip = False
        for line in lines:
            if line == MARKER_BEGIN:
                skip = True
                continue
            if line == MARKER_END:
                skip = False
                continue
            if not skip:
                out.append(line)
        # Strip trailing blank lines
        while out and out[-1] == "":
            out.pop()
        return "\n".join(out)

    def build_managed_block(self, entries: list[CronEntry]) -> str:
        if not entries:
            return ""
        return "\n".join(e.to_crontab_lines() for e in entries)

    def assemble(self, unmanaged: str, managed: str) -> str:
        parts: list[str] = []
        if unmanaged:
            parts.append(unmanaged)
        if managed:
            parts.append(MARKER_BEGIN)
            parts.append("")
            parts.append(managed)
            parts.append("")
            parts.append(MARKER_END)
        result = "\n".join(parts)
        if result and not result.endswith("\n"):
            result += "\n"
        return result

    def apply(self, new_crontab: str, dry_run: bool = False) -> bool:
        current = self.get_current()
        if new_crontab == current:
            return False
        if dry_run:
            return True
        subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            text=True,
            check=True,
        )
        return True
