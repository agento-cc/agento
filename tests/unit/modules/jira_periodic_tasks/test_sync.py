from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from agento.modules.jira.src.config import JiraConfig
from agento.modules.jira_periodic_tasks.src.crontab import CronEntry, CrontabManager
from agento.modules.jira_periodic_tasks.src.sync import JiraCronSync


def test_build_jql_without_assignee(sample_config, sample_periodic_config):
    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    jql = syncer.build_jql()
    assert jql == 'project = AI AND status = "Cykliczne"'


def test_build_jql_with_assignee(sample_periodic_config):
    config = JiraConfig(
        toolbox_url="http://toolbox:3001",
        user="bot@test.com",
        jira_projects=["AI"],
        jira_assignee="bot@test.com",
    )
    syncer = JiraCronSync(config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    jql = syncer.build_jql()
    assert 'AND assignee = "bot@test.com"' in jql


def test_parse_issues_valid(sample_config, sample_periodic_config, jira_cykliczne):
    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    entries = syncer.parse_issues(jira_cykliczne)

    # AI-2 (Co 5min) and AI-3 (1x dziennie o 8:00) should be parsed
    # AI-4 (null frequency) and AI-5 (unknown frequency) should be skipped
    assert len(entries) == 2
    assert entries[0].issue_key == "AI-2"
    assert entries[0].cron_expression == "*/5 * * * *"
    assert entries[1].issue_key == "AI-3"
    assert entries[1].cron_expression == "0 8 * * *"


def test_parse_issues_skip_null_frequency(sample_config, sample_periodic_config, jira_cykliczne, caplog):
    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    with caplog.at_level(logging.WARNING):
        syncer.parse_issues(jira_cykliczne)

    assert any("AI-4" in r.message and "no frequency" in r.message for r in caplog.records)


def test_parse_issues_skip_unknown_frequency(sample_config, sample_periodic_config, jira_cykliczne, caplog):
    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    with caplog.at_level(logging.WARNING):
        syncer.parse_issues(jira_cykliczne)

    assert any("AI-5" in r.message and "unknown frequency" in r.message for r in caplog.records)


def test_parse_issues_empty(sample_config, sample_periodic_config, jira_empty):
    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    entries = syncer.parse_issues(jira_empty)
    assert entries == []


def test_full_sync_dry_run(sample_config, sample_periodic_config, jira_cykliczne):
    toolbox = MagicMock()
    toolbox.jira_search.return_value = jira_cykliczne

    crontab = CrontabManager()
    # Mock subprocess calls
    crontab.get_current = MagicMock(return_value="SHELL=/bin/bash\n")
    crontab.apply = MagicMock(return_value=True)

    logger = logging.getLogger("test-sync")
    syncer = JiraCronSync(sample_config, sample_periodic_config, toolbox, crontab, logger)
    syncer._do_sync(dry_run=True)

    # Verify apply was called with dry_run=True
    crontab.apply.assert_called_once()
    _, kwargs = crontab.apply.call_args
    assert kwargs["dry_run"] is True


def test_full_sync_generates_correct_crontab(sample_config, sample_periodic_config, jira_cykliczne):
    toolbox = MagicMock()
    toolbox.jira_search.return_value = jira_cykliczne

    crontab = CrontabManager()
    crontab.get_current = MagicMock(return_value="SHELL=/bin/bash\n")
    applied_crontab = None

    def capture_apply(new_crontab, dry_run=False):
        nonlocal applied_crontab
        applied_crontab = new_crontab
        return True

    crontab.apply = capture_apply

    logger = logging.getLogger("test-sync")
    syncer = JiraCronSync(sample_config, sample_periodic_config, toolbox, crontab, logger)
    syncer._do_sync(dry_run=False)

    assert applied_crontab is not None
    assert "SHELL=/bin/bash" in applied_crontab
    assert "JIRA-SYNC:BEGIN" in applied_crontab
    assert "JIRA-SYNC:END" in applied_crontab
    assert "AI-2" in applied_crontab
    assert "*/5 * * * *" in applied_crontab
    assert "AI-3" in applied_crontab
    assert "0 8 * * *" in applied_crontab
    # Skipped issues should not appear
    assert "AI-4" not in applied_crontab
    assert "AI-5" not in applied_crontab


# ---- Schedules upsert tests ----


def _mock_connection():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def _sample_entries():
    return [
        CronEntry(issue_key="AI-2", summary="Task 2", frequency_label="Co 5min", cron_expression="*/5 * * * *"),
        CronEntry(issue_key="AI-3", summary="Task 3", frequency_label="1x dziennie o 8:00", cron_expression="0 8 * * *"),
    ]


@patch("agento.modules.jira_periodic_tasks.src.sync.get_connection")
def test_upsert_schedules_inserts(mock_get_conn, sample_config, sample_periodic_config, jira_cykliczne):
    mock_conn, mock_cursor = _mock_connection()
    mock_get_conn.return_value = mock_conn

    entries = _sample_entries()

    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    syncer._upsert_schedules(entries)

    # One INSERT per entry + one UPDATE for removed entries
    assert mock_cursor.execute.call_count == 3
    first_sql = mock_cursor.execute.call_args_list[0][0][0]
    assert "INSERT INTO schedule" in first_sql
    assert "ON DUPLICATE KEY UPDATE" in first_sql
    mock_conn.commit.assert_called_once()


@patch("agento.modules.jira_periodic_tasks.src.sync.get_connection")
def test_upsert_schedules_disables_removed(mock_get_conn, sample_config, sample_periodic_config):
    mock_conn, mock_cursor = _mock_connection()
    mock_get_conn.return_value = mock_conn

    entries = _sample_entries()

    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    syncer._upsert_schedules(entries)

    # Last call should be the UPDATE for non-listed keys
    last_call = mock_cursor.execute.call_args_list[-1]
    sql = last_call[0][0]
    assert "enabled = FALSE" in sql
    assert "NOT IN" in sql


@patch("agento.modules.jira_periodic_tasks.src.sync.get_connection")
def test_upsert_schedules_empty_disables_all(mock_get_conn, sample_config, sample_periodic_config):
    mock_conn, mock_cursor = _mock_connection()
    mock_get_conn.return_value = mock_conn

    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))
    syncer._upsert_schedules([])

    # With empty entries, should disable all schedules
    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "enabled = FALSE" in sql
    assert "NOT IN" not in sql


@patch("agento.modules.jira_periodic_tasks.src.sync.get_connection")
def test_upsert_schedules_db_error_logged(mock_get_conn, sample_config, sample_periodic_config, caplog):
    mock_conn, mock_cursor = _mock_connection()
    mock_cursor.execute.side_effect = RuntimeError("DB error")
    mock_get_conn.return_value = mock_conn

    syncer = JiraCronSync(sample_config, sample_periodic_config, MagicMock(), MagicMock(), logging.getLogger("test"))

    with caplog.at_level(logging.WARNING):
        syncer._upsert_schedules(_sample_entries())

    mock_conn.rollback.assert_called_once()


def test_sync_emits_single_summary_line(sample_config, sample_periodic_config, jira_cykliczne, caplog):
    toolbox = MagicMock()
    toolbox.jira_search.return_value = jira_cykliczne

    crontab = CrontabManager()
    crontab.get_current = MagicMock(return_value="SHELL=/bin/bash\n")
    crontab.apply = MagicMock(return_value=False)

    logger = logging.getLogger("test-sync-summary")
    syncer = JiraCronSync(sample_config, sample_periodic_config, toolbox, crontab, logger)

    with caplog.at_level(logging.INFO):
        syncer._do_sync(dry_run=True)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert info_records[0].message.startswith("Sync OK")
    assert "2 entries" in info_records[0].message


@patch("agento.modules.jira_periodic_tasks.src.sync.get_connection")
def test_upsert_schedules_skipped_in_dry_run(mock_get_conn, sample_config, sample_periodic_config, jira_cykliczne):
    toolbox = MagicMock()
    toolbox.jira_search.return_value = jira_cykliczne

    crontab = CrontabManager()
    crontab.get_current = MagicMock(return_value="SHELL=/bin/bash\n")
    crontab.apply = MagicMock(return_value=True)

    syncer = JiraCronSync(sample_config, sample_periodic_config, toolbox, crontab, logging.getLogger("test"))
    syncer._do_sync(dry_run=True)

    # get_connection should NOT have been called (upsert skipped in dry_run)
    mock_get_conn.assert_not_called()
