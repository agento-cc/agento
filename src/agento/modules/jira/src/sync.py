from __future__ import annotations

import logging

from agento.framework.db import get_connection
from agento.framework.lock import FileLock, LockHeld

from .crontab import CronEntry, CrontabManager
from .toolbox_client import ToolboxClient


class JiraCronSync:

    def __init__(
        self,
        config: object,
        toolbox: ToolboxClient,
        crontab: CrontabManager,
        logger: logging.Logger,
        *,
        db_config: object | None = None,
    ):
        self.config = config
        self.db_config = db_config
        self.toolbox = toolbox
        self.crontab = crontab
        self.logger = logger

    def build_jql(self) -> str:
        jql = f'{self.config.jira_project_jql} AND status = "{self.config.jira_status}"'
        if self.config.jira_assignee:
            jql += f' AND assignee = "{self.config.jira_assignee}"'
        return jql

    def resolve_frequency(self, freq_value: str) -> str | None:
        return self.config.frequency_map.get(freq_value)

    def parse_issues(self, response: dict) -> list[CronEntry]:
        entries: list[CronEntry] = []
        freq_field = self.config.jira_frequency_field

        for issue in response.get("issues", []):
            key = issue["key"]
            summary = issue.get("fields", {}).get("summary", "")
            freq_obj = issue.get("fields", {}).get(freq_field)

            if freq_obj is None:
                self.logger.warning(f"Issue {key} has no frequency set. Skipping.")
                continue

            freq_value = freq_obj.get("value") if isinstance(freq_obj, dict) else None
            if not freq_value:
                self.logger.warning(f"Issue {key} has no frequency value. Skipping.")
                continue

            cron_expr = self.resolve_frequency(freq_value)
            if not cron_expr:
                self.logger.warning(f"Issue {key} has unknown frequency '{freq_value}'. Skipping.")
                continue

            entries.append(CronEntry(
                issue_key=key,
                summary=summary,
                frequency_label=freq_value,
                cron_expression=cron_expr,
            ))

        return entries

    def sync(self, dry_run: bool = False) -> None:
        try:
            lock = FileLock()
            with lock:
                self._do_sync(dry_run)
        except LockHeld as e:
            self.logger.warning(f"Another sync is running ({e}). Exiting.")

    def _do_sync(self, dry_run: bool) -> None:
        self.logger.debug(
            f"Starting Jira->cron sync (projects={self.config.jira_projects}, "
            f"status={self.config.jira_status})"
        )

        response = self.toolbox.jira_search(
            jql=self.build_jql(),
            fields=["key", "summary", self.config.jira_frequency_field],
            max_results=50,
        )

        issues = response.get("issues", [])
        self.logger.debug(f"Found {len(issues)} issues in Jira with status '{self.config.jira_status}'.")

        entries = self.parse_issues(response)
        self.logger.debug(f"Generated {len(entries)} cron entries.")

        managed = self.crontab.build_managed_block(entries)
        current = self.crontab.get_current()
        unmanaged = self.crontab.extract_unmanaged(current)
        new_crontab = self.crontab.assemble(unmanaged, managed)

        changed = self.crontab.apply(new_crontab, dry_run=dry_run)

        schedules_synced = 0
        if not dry_run:
            schedules_synced = self._upsert_schedules(entries)

        # Single summary line
        parts = [
            f"{len(issues)} issues",
            f"{len(entries)} entries",
            ("crontab updated" if changed else "crontab unchanged"),
        ]
        if not dry_run:
            parts.append(f"{schedules_synced} schedules")

        prefix = "Sync OK [DRY RUN]" if dry_run else "Sync OK"
        self.logger.info(f"{prefix}: {', '.join(parts)}")

    def _upsert_schedules(self, entries: list[CronEntry]) -> int:
        """Sync schedules table with current Jira entries. Returns count synced."""
        try:
            conn = get_connection(self.db_config or self.config)
        except Exception:
            self.logger.warning("Cannot connect to MySQL for schedules upsert, skipping.")
            return 0

        try:
            with conn.cursor() as cur:
                for entry in entries:
                    cur.execute(
                        """
                        INSERT INTO schedule (issue_key, summary, agent_type, cron_expr, enabled)
                        VALUES (%s, %s, 'cron', %s, TRUE)
                        ON DUPLICATE KEY UPDATE
                            summary = VALUES(summary),
                            cron_expr = VALUES(cron_expr),
                            enabled = TRUE,
                            updated_at = NOW()
                        """,
                        (entry.issue_key, entry.summary, entry.cron_expression),
                    )
                if entries:
                    keys = [e.issue_key for e in entries]
                    placeholders = ",".join(["%s"] * len(keys))
                    cur.execute(
                        f"UPDATE schedule SET enabled = FALSE, updated_at = NOW() "
                        f"WHERE issue_key NOT IN ({placeholders})",
                        keys,
                    )
                else:
                    cur.execute("UPDATE schedule SET enabled = FALSE, updated_at = NOW()")
            conn.commit()
            self.logger.debug(f"Schedules table synced ({len(entries)} entries).")
            return len(entries)
        except Exception:
            conn.rollback()
            self.logger.exception("Failed to upsert schedules table.")
            return 0
        finally:
            conn.close()
