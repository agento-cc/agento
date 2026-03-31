from __future__ import annotations

from agento.modules.jira_periodic_tasks.src.crontab import MARKER_BEGIN, MARKER_END, CronEntry, CrontabManager


def test_extract_unmanaged_with_markers():
    mgr = CrontabManager()
    crontab = (
        "SHELL=/bin/bash\n"
        "* * * * * /some/job\n"
        f"{MARKER_BEGIN}\n"
        "# AI-2: Task (Co 5min)\n"
        "*/5 * * * * /opt/cron-agent/run.sh exec:cron AI-2\n"
        f"{MARKER_END}\n"
    )
    result = mgr.extract_unmanaged(crontab)
    assert MARKER_BEGIN not in result
    assert MARKER_END not in result
    assert "SHELL=/bin/bash" in result
    assert "* * * * * /some/job" in result
    assert "AI-2" not in result


def test_extract_unmanaged_no_markers():
    mgr = CrontabManager()
    crontab = "SHELL=/bin/bash\n* * * * * /some/job\n"
    result = mgr.extract_unmanaged(crontab)
    assert "SHELL=/bin/bash" in result
    assert "* * * * * /some/job" in result


def test_extract_unmanaged_strips_trailing_blanks():
    mgr = CrontabManager()
    crontab = "line1\nline2\n\n\n"
    result = mgr.extract_unmanaged(crontab)
    assert result == "line1\nline2"


def test_build_managed_block():
    mgr = CrontabManager()
    entries = [
        CronEntry(issue_key="AI-2", summary="Check logs", frequency_label="Co 5min", cron_expression="*/5 * * * *"),
        CronEntry(issue_key="AI-3", summary="Daily report", frequency_label="1x dziennie o 8:00", cron_expression="0 8 * * *"),
    ]
    block = mgr.build_managed_block(entries)
    assert "# AI-2: Check logs (Co 5min)" in block
    assert "*/5 * * * *" in block
    assert "# AI-3: Daily report" in block
    assert "0 8 * * *" in block


def test_build_managed_block_empty():
    mgr = CrontabManager()
    assert mgr.build_managed_block([]) == ""


def test_assemble_with_managed_and_unmanaged():
    mgr = CrontabManager()
    result = mgr.assemble("SHELL=/bin/bash", "# AI-2\n*/5 * * * * cmd")
    assert result.startswith("SHELL=/bin/bash\n")
    assert MARKER_BEGIN in result
    assert MARKER_END in result
    assert "# AI-2" in result
    assert result.endswith("\n")


def test_assemble_empty_managed():
    mgr = CrontabManager()
    result = mgr.assemble("SHELL=/bin/bash", "")
    assert MARKER_BEGIN not in result
    assert "SHELL=/bin/bash" in result


def test_assemble_empty_unmanaged():
    mgr = CrontabManager()
    result = mgr.assemble("", "# AI-2\ncmd")
    assert MARKER_BEGIN in result
    assert "# AI-2" in result


def test_cron_entry_to_crontab_lines():
    entry = CronEntry(
        issue_key="AI-2",
        summary="Check logs",
        frequency_label="Co 5min",
        cron_expression="*/5 * * * *",
    )
    lines = entry.to_crontab_lines()
    assert lines.startswith("# AI-2: Check logs (Co 5min)\n")
    assert "*/5 * * * * set -a; source /opt/cron-agent/env; set +a; cd /workspace && /opt/cron-agent/run.sh publish jira-cron AI-2" in lines


def test_cron_entry_command_sources_env_file():
    """Managed crontab commands must source the env file so cron jobs
    get MYSQL_* variables that cron doesn't inherit from Docker."""
    entry = CronEntry(
        issue_key="AI-99",
        summary="Any task",
        frequency_label="Co 5min",
        cron_expression="*/5 * * * *",
    )
    assert entry.command.startswith("set -a; source /opt/cron-agent/env; set +a;")
    assert "/opt/cron-agent/run.sh publish jira-cron AI-99" in entry.command
