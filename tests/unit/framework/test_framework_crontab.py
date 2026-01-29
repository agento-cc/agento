"""Tests for framework crontab manager (Phase 7)."""
from __future__ import annotations

import json
from pathlib import Path

from agento.framework.crontab import (
    MARKER_BEGIN,
    MARKER_END,
    CronJob,
    assemble,
    build_managed_block,
    collect_cron_jobs,
    extract_unmanaged,
)
from agento.framework.module_loader import ModuleManifest


def _manifest(name: str, cron: dict) -> ModuleManifest:
    return ModuleManifest(
        name=name, version="1.0.0", description="", path=Path("/fake"),
        cron=cron,
    )


class TestCronJob:
    def test_full_command_wraps_with_run_sh(self):
        job = CronJob(name="test", schedule="* * * * *", command="sync")

        assert "run.sh sync" in job.full_command
        assert "source" in job.full_command

    def test_raw_command_bypasses_wrapping(self):
        job = CronJob(name="logrotate", schedule="0 2 * * *", raw_command="/usr/sbin/logrotate conf")

        assert job.full_command == "/usr/sbin/logrotate conf"

    def test_to_crontab_line(self):
        job = CronJob(name="jira/sync", schedule="0 * * * *", command="sync")

        line = job.to_crontab_line()

        assert line.startswith("# jira/sync\n")
        assert "0 * * * *" in line


class TestCollectCronJobs:
    def test_collects_from_manifests(self):
        m = _manifest("jira", {"jobs": [
            {"name": "sync", "schedule": "0 * * * *", "command": "sync"},
            {"name": "publish", "schedule": "* * * * *", "command": "publish jira-todo"},
        ]})

        jobs = collect_cron_jobs([m])

        assert len(jobs) == 2
        assert jobs[0].name == "jira/sync"
        assert jobs[1].name == "jira/publish"

    def test_includes_framework_jobs(self, tmp_path):
        fw_path = tmp_path / "cron.json"
        fw_path.write_text(json.dumps({"jobs": [
            {"name": "logrotate", "schedule": "0 2 * * *", "raw_command": "/usr/sbin/logrotate conf"},
        ]}))

        jobs = collect_cron_jobs([], framework_crontab_path=fw_path)

        assert len(jobs) == 1
        assert jobs[0].name == "logrotate"
        assert jobs[0].raw_command == "/usr/sbin/logrotate conf"

    def test_framework_jobs_before_module_jobs(self, tmp_path):
        fw_path = tmp_path / "cron.json"
        fw_path.write_text(json.dumps({"jobs": [
            {"name": "logrotate", "schedule": "0 2 * * *", "raw_command": "logrotate"},
        ]}))
        m = _manifest("jira", {"jobs": [
            {"name": "sync", "schedule": "0 * * * *", "command": "sync"},
        ]})

        jobs = collect_cron_jobs([m], framework_crontab_path=fw_path)

        assert jobs[0].name == "logrotate"
        assert jobs[1].name == "jira/sync"

    def test_empty_when_no_declarations(self):
        m = _manifest("jira", {})

        assert collect_cron_jobs([m]) == []

    def test_missing_framework_path(self):
        assert collect_cron_jobs([], framework_crontab_path=Path("/nonexistent")) == []


class TestExtractUnmanaged:
    def test_removes_agento_block(self):
        crontab = (
            "SHELL=/bin/bash\n"
            f"{MARKER_BEGIN}\n"
            "# logrotate\n"
            "0 2 * * * /usr/sbin/logrotate conf\n"
            f"{MARKER_END}\n"
        )

        result = extract_unmanaged(crontab)

        assert MARKER_BEGIN not in result
        assert MARKER_END not in result
        assert "logrotate" not in result
        assert "SHELL=/bin/bash" in result

    def test_preserves_jira_sync_block(self):
        jira_begin = "# JIRA-SYNC:BEGIN - Auto-generated. Do not edit manually."
        jira_end = "# JIRA-SYNC:END"
        crontab = (
            "SHELL=/bin/bash\n"
            f"{MARKER_BEGIN}\n"
            "# logrotate\n"
            f"{MARKER_END}\n"
            f"{jira_begin}\n"
            "* * * * * run.sh publish jira-cron PROJ-123\n"
            f"{jira_end}\n"
        )

        result = extract_unmanaged(crontab)

        assert jira_begin in result
        assert "PROJ-123" in result
        assert jira_end in result
        assert MARKER_BEGIN not in result

    def test_no_agento_block(self):
        crontab = "SHELL=/bin/bash\nPATH=/usr/bin\n"

        result = extract_unmanaged(crontab)

        assert result == "SHELL=/bin/bash\nPATH=/usr/bin"


class TestBuildManagedBlock:
    def test_formats_jobs(self):
        jobs = [
            CronJob(name="logrotate", schedule="0 2 * * *", raw_command="logrotate conf"),
            CronJob(name="jira/sync", schedule="0 * * * *", command="sync"),
        ]

        block = build_managed_block(jobs)

        assert "# logrotate" in block
        assert "# jira/sync" in block
        assert "0 2 * * * logrotate conf" in block

    def test_empty_jobs(self):
        assert build_managed_block([]) == ""


class TestAssemble:
    def test_combines_unmanaged_and_managed(self):
        unmanaged = "SHELL=/bin/bash\nPATH=/usr/bin"
        managed = "# logrotate\n0 2 * * * logrotate conf"

        result = assemble(unmanaged, managed)

        assert result.startswith("SHELL=/bin/bash")
        assert MARKER_BEGIN in result
        assert MARKER_END in result
        assert "logrotate" in result
        assert result.endswith("\n")

    def test_empty_managed(self):
        result = assemble("SHELL=/bin/bash", "")

        assert MARKER_BEGIN not in result
        assert "SHELL=/bin/bash" in result

    def test_empty_unmanaged(self):
        result = assemble("", "# job\n* * * * * cmd")

        assert MARKER_BEGIN in result
        assert "# job" in result

    def test_both_empty(self):
        assert assemble("", "") == ""
