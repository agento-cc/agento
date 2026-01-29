# Test Plan: Job Orchestration (Publisher-Consumer)

Covers new modules: `publisher.py`, `jira_publisher.py`, `consumer.py`, `retry_policy.py`, `job_models.py`, `db.py`.
All DB access mocked via `unittest.mock.patch` on `app.db.get_connection`. No real MySQL needed.

---

## 1. retry_policy (test_retry_policy.py)

Pure logic, no mocks needed.

| Test | What it verifies |
|------|-----------------|
| `test_retryable_error_attempt_1` | First failure → should_retry=True, delay=60s |
| `test_retryable_error_attempt_2` | Second failure → should_retry=True, delay=300s |
| `test_retryable_error_attempt_3_max_reached` | Third failure with max_attempts=3 → should_retry=False |
| `test_non_retryable_value_error` | `ValueError` → should_retry=False immediately |
| `test_non_retryable_permission_error` | `PermissionError` → should_retry=False |
| `test_non_retryable_key_error` | `KeyError` → should_retry=False |
| `test_unknown_error_is_retryable` | `RuntimeError` (not in blocklist) → should_retry=True |
| `test_none_error_class_is_retryable` | `error_class=None` → should_retry=True |
| `test_backoff_caps_at_last_delay` | attempt=10 → delay still 1800s (last in list) |

## 2. job_models (test_job_models.py)

| Test | What it verifies |
|------|-----------------|
| `test_job_from_row` | `Job.from_row()` maps all dict fields correctly |
| `test_job_from_row_nullable_fields` | Handles `None` for `schedule_id`, `issue_key`, `started_at`, etc. |
| `test_agent_type_enum` | `AgentType("cron")` == `AgentType.CRON`, invalid value raises |
| `test_job_status_enum` | All 5 statuses parse correctly |

## 3. publisher (test_publisher.py)

Mock: `app.db.get_connection` → returns a mock connection with mock cursor.

| Test | What it verifies |
|------|-----------------|
| `test_publish_inserts_job` | Calls INSERT IGNORE with correct params, returns `True` when `rowcount=1` |
| `test_publish_duplicate_returns_false` | When `rowcount=0` (INSERT IGNORE hit duplicate), returns `False` |
| `test_publish_commits_on_success` | `conn.commit()` called |
| `test_publish_rollback_on_error` | If cursor.execute raises, `conn.rollback()` called, exception propagated |
| `test_publish_closes_connection` | `conn.close()` always called (success and failure) |

## 4. jira_publisher (test_jira_publisher.py)

Mock: `app.publisher.publish` (patch the generic function to verify args).

| Test | What it verifies |
|------|-----------------|
| `test_idempotency_key_cron` | `build_idempotency_key(CRON, "AI-123")` → `jira:cron:AI-123:YYYYMMDD_HHMM` |
| `test_idempotency_key_todo_with_issue` | `build_idempotency_key(TODO, "AI-456")` → `jira:todo:AI-456:YYYYMMDD_HHMM` |
| `test_idempotency_key_todo_dispatch` | `build_idempotency_key(TODO, None)` → `jira:todo:dispatch:YYYYMMDD_HH` (hour-granular) |
| `test_publish_cron_calls_generic_publish` | `publish_cron(config, "AI-123")` calls `publish()` with `agent_type=CRON, source="jira"` |
| `test_publish_todo_dispatch` | `publish_todo(config, None)` calls `publish()` with `agent_type=TODO, issue_key=None` |
| `test_publish_todo_specific_issue` | `publish_todo(config, "AI-789")` calls `publish()` with `issue_key="AI-789"` |
| `test_idempotency_key_same_minute_is_stable` | Two calls in the same minute produce the same key (frozen time) |
| `test_idempotency_key_different_minute_differs` | Two calls in different minutes produce different keys |

## 5. consumer — dequeue (test_consumer.py)

Mock: `app.db.get_connection` → mock connection/cursor.

| Test | What it verifies |
|------|-----------------|
| `test_dequeue_empty_queue` | Cursor returns `None` → `_try_dequeue()` returns `None`, rollback called |
| `test_dequeue_claims_job` | Cursor returns a row → executes CLAIM_SQL, commits, returns `Job` with status=RUNNING |
| `test_dequeue_increments_attempt` | Returned `Job.attempt` is row's `attempt + 1` |
| `test_dequeue_error_returns_none` | If cursor.execute raises → returns `None`, rollback called, logged |
| `test_dequeue_always_closes_connection` | `conn.close()` called in success and failure paths |

## 6. consumer — execution dispatch (test_consumer.py)

Mock: `ClaudeRunner`, `CronTaskExecutor`, `TodoTaskExecutor`, `TaskListBuilder`, `app.db.get_connection`.

| Test | What it verifies |
|------|-----------------|
| `test_run_job_cron` | `agent_type=CRON, issue_key="AI-1"` → calls `CronTaskExecutor.execute("AI-1")` |
| `test_run_job_cron_no_issue_key_raises` | `agent_type=CRON, issue_key=None` → raises `ValueError` |
| `test_run_job_todo_specific` | `agent_type=TODO, issue_key="AI-2"` → calls `TodoTaskExecutor.execute("AI-2")` |
| `test_run_job_todo_dispatch` | `agent_type=TODO, issue_key=None` → queries TaskListBuilder, picks first, executes |
| `test_run_job_todo_dispatch_no_tasks` | TaskListBuilder returns `[]` → returns "No TODO tasks found" |
| `test_run_job_todo_dispatch_updates_issue_key` | After picking a task, `_update_job_issue_key` is called with discovered key |

## 7. consumer — finalization (test_consumer.py)

Mock: `app.db.get_connection`, `app.retry_policy.evaluate`.

| Test | What it verifies |
|------|-----------------|
| `test_finalize_success` | `error=None` → UPDATE status='SUCCESS', `result_summary` stored, commit |
| `test_finalize_retryable_failure` | `evaluate` returns `should_retry=True, delay=60` → status='TODO', `scheduled_after` in future |
| `test_finalize_non_retryable_failure` | `evaluate` returns `should_retry=False` → status='DEAD' |
| `test_finalize_max_attempts_reached` | attempt=3, max=3 → `evaluate` says no retry → DEAD |
| `test_finalize_error_message_truncated` | Error message >2000 chars → truncated to 2000 |
| `test_finalize_db_error_does_not_crash` | If UPDATE raises → logged, no exception propagated |

## 8. consumer — lifecycle (test_consumer.py)

| Test | What it verifies |
|------|-----------------|
| `test_shutdown_on_sigterm` | Calling `_handle_signal(SIGTERM)` sets `_shutdown` event |
| `test_poll_loop_exits_on_shutdown` | With `_shutdown` set, `run()` exits after current iteration |

## 9. log — JsonFormatter (test_log.py)

| Test | What it verifies |
|------|-----------------|
| `test_json_formatter_basic` | Produces valid JSON with `ts`, `level`, `logger`, `msg` |
| `test_json_formatter_extra_fields` | Extra fields (`job_id`, `issue_key`) included in output |
| `test_json_formatter_exception` | When `exc_info` present, `error` and `error_class` fields added |
| `test_json_formatter_missing_extras_omitted` | Extra fields not set → not in JSON output |

## 10. config — new fields (extend test_config.py)

| Test | What it verifies |
|------|-----------------|
| `test_mysql_defaults` | Config without MySQL env vars → defaults (`mysql`, 3306, `cron_agent`) |
| `test_mysql_from_env` | With `MYSQL_HOST=dbhost` env var → `config.mysql_host == "dbhost"` |
| `test_consumer_config_from_json` | JSON with `"consumer": {"concurrency": 4}` → `config.consumer_concurrency == 4` |
| `test_consumer_config_defaults` | JSON without `consumer` section → defaults (2, 5.0) |

## 11. sync — schedules upsert (extend test_sync.py)

Mock: `app.db.get_connection`.

| Test | What it verifies |
|------|-----------------|
| `test_upsert_schedules_inserts` | Calls INSERT ON DUPLICATE for each entry |
| `test_upsert_schedules_disables_removed` | Entries not in list → UPDATE enabled=FALSE |
| `test_upsert_schedules_empty_disables_all` | Empty entries list → all schedules disabled |
| `test_upsert_schedules_db_error_logged` | On exception → logged as warning, sync continues |
| `test_upsert_schedules_skipped_in_dry_run` | `_do_sync(dry_run=True)` → `_upsert_schedules` not called |

---

## Mocking strategy

All tests use `unittest.mock.patch` / `MagicMock`. Pattern:

```python
from unittest.mock import MagicMock, patch

@patch("src.db.get_connection")
def test_publish_inserts_job(mock_get_conn, sample_config):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_conn.return_value = mock_conn

    result = publish(sample_config, AgentType.CRON, "jira", "key:1", issue_key="AI-1")

    assert result is True
    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()
```

For `jira_publisher` tests, mock `app.publisher.publish` directly to verify it receives correct args without touching DB at all.

For consumer tests, mock `ClaudeRunner` to return a canned `ClaudeResult` and mock `app.db.get_connection` for dequeue/finalize operations.

Use `freezegun` or `unittest.mock.patch("src.jira_publisher.datetime")` for time-dependent idempotency key tests.

## Test file summary

| File | Tests | Covers |
|------|-------|--------|
| `test_retry_policy.py` | 9 | Backoff delays, retryable vs non-retryable classification |
| `test_job_models.py` | 4 | Job.from_row(), enum parsing |
| `test_publisher.py` | 5 | Generic publish(), INSERT IGNORE, commit/rollback/close |
| `test_jira_publisher.py` | 8 | Idempotency key generation, cron/todo/dispatch variants |
| `test_consumer.py` | ~14 | Dequeue, dispatch, finalization, retry/dead-letter, lifecycle |
| `test_log.py` | 4 | JsonFormatter output |
| `test_config.py` | +4 | MySQL + consumer config fields |
| `test_sync.py` | +5 | Schedules upsert |
| **Total new** | **~49** | |
