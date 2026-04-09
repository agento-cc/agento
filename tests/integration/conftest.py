"""Integration test fixtures — real MySQL, mocked HTTP & Claude."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pymysql
import pytest
from pymysql.cursors import DictCursor

from agento.framework.bootstrap import bootstrap, set_module_config
from agento.framework.consumer_config import ConsumerConfig
from agento.framework.database_config import DatabaseConfig
from agento.framework.migrate import migrate
from agento.modules.claude.src.output_parser import ClaudeResult
from agento.modules.jira.src.config import JiraConfig
from agento.modules.jira_periodic_tasks.src.config import PeriodicTasksConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

TEST_DB = "cron_agent_test"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _root_connection() -> pymysql.Connection:
    """Connect as root (no database selected) to create/drop test DB."""
    return pymysql.connect(
        host=os.environ.get("TEST_MYSQL_HOST", "localhost"),
        port=int(os.environ.get("TEST_MYSQL_PORT", "3306")),
        user=os.environ.get("TEST_MYSQL_USER", "root"),
        password=os.environ.get("TEST_MYSQL_PASSWORD", "cronagent_root"),
        charset="utf8mb4",
        autocommit=True,
    )


def _test_connection(autocommit: bool = False) -> pymysql.Connection:
    """Connect to the test database."""
    return pymysql.connect(
        host=os.environ.get("TEST_MYSQL_HOST", "localhost"),
        port=int(os.environ.get("TEST_MYSQL_PORT", "3306")),
        user=os.environ.get("TEST_MYSQL_USER", "root"),
        password=os.environ.get("TEST_MYSQL_PASSWORD", "cronagent_root"),
        database=TEST_DB,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=autocommit,
    )


# ---------------------------------------------------------------------------
# Session-scoped: create/destroy test database
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _create_test_db():
    """Create test database + apply all migrations once per session, drop on teardown."""
    conn = _root_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            cur.execute(
                f"CREATE DATABASE {TEST_DB} "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()

    # Apply framework migrations
    conn = _test_connection(autocommit=False)
    try:
        migrate(conn)
    finally:
        conn.close()

    # Apply module SQL migrations (same as setup:upgrade does)
    from agento.framework.bootstrap import CORE_MODULES_DIR
    from agento.framework.module_loader import scan_modules
    all_modules = scan_modules(CORE_MODULES_DIR)
    conn = _test_connection(autocommit=False)
    try:
        for m in all_modules:
            sql_dir = m.path / "sql"
            if sql_dir.is_dir():
                migrate(conn, module=m.name, sql_dir=sql_dir)
    finally:
        conn.close()

    yield

    conn = _root_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Function-scoped: config, connection, table cleanup
# ---------------------------------------------------------------------------

@pytest.fixture
def int_db_config() -> DatabaseConfig:
    """DatabaseConfig pointing to the test MySQL database."""
    return DatabaseConfig(
        mysql_host=os.environ.get("TEST_MYSQL_HOST", "localhost"),
        mysql_port=int(os.environ.get("TEST_MYSQL_PORT", "3306")),
        mysql_database=TEST_DB,
        mysql_user=os.environ.get("TEST_MYSQL_USER", "root"),
        mysql_password=os.environ.get("TEST_MYSQL_PASSWORD", "cronagent_root"),
    )


@pytest.fixture
def int_consumer_config() -> ConsumerConfig:
    """ConsumerConfig for integration tests."""
    return ConsumerConfig()


@pytest.fixture
def int_config() -> JiraConfig:
    """JiraConfig for integration tests (backward-compat fixture name)."""
    return JiraConfig(
        toolbox_url="http://toolbox:3001",
        user="agenty@example.com",
        jira_projects=["AI"],
        jira_assignee="agenty@example.com",
    )


@pytest.fixture
def int_periodic_config() -> PeriodicTasksConfig:
    """PeriodicTasksConfig for integration tests."""
    return PeriodicTasksConfig(
        jira_status="Cykliczne",
        jira_frequency_field="customfield_10709",
        frequency_map={
            "Co 5min": "*/5 * * * *",
            "Co 30min": "*/30 * * * *",
            "Co 1h": "0 * * * *",
            "Co 4h": "0 */4 * * *",
            "1x dziennie o 8:00": "0 8 * * *",
            "1x dziennie o 1:00 w nocy": "0 1 * * *",
            "2x dziennie o 6:00 i 18:00": "0 6,18 * * *",
            "1x w tygodniu (Pon, 7:00)": "0 7 * * 1",
        },
    )


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_registries():
    """Populate registries from core modules (once per session)."""
    bootstrap()
    # Override module configs with integration test values
    set_module_config("jira", JiraConfig(
        toolbox_url="http://toolbox:3001",
        user="agenty@example.com",
        jira_projects=["AI"],
        jira_assignee="agenty@example.com",
    ))
    set_module_config("jira_periodic_tasks", PeriodicTasksConfig(
        jira_status="Cykliczne",
        jira_frequency_field="customfield_10709",
        frequency_map={
            "Co 5min": "*/5 * * * *",
            "Co 30min": "*/30 * * * *",
            "Co 1h": "0 * * * *",
            "Co 4h": "0 */4 * * *",
            "1x dziennie o 8:00": "0 8 * * *",
            "1x dziennie o 1:00 w nocy": "0 1 * * *",
            "2x dziennie o 6:00 i 18:00": "0 6,18 * * *",
            "1x w tygodniu (Pon, 7:00)": "0 7 * * 1",
        },
    ))


@pytest.fixture(autouse=True)
def _truncate_tables():
    """Truncate all tables before each test for isolation."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            cur.execute("TRUNCATE TABLE job")
            cur.execute("TRUNCATE TABLE schedule")
            cur.execute("TRUNCATE TABLE usage_log")
            cur.execute("TRUNCATE TABLE oauth_token")
            cur.execute("TRUNCATE TABLE skill_registry")
            cur.execute("TRUNCATE TABLE workspace_build")
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

def insert_primary_token(agent_type: str = "claude", model: str | None = None) -> int:
    """Insert an enabled, primary oauth_token and return its id."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE oauth_token SET is_primary = FALSE WHERE is_primary = TRUE")
            cur.execute(
                """
                INSERT INTO oauth_token
                    (agent_type, label, credentials_path, is_primary, enabled, model)
                VALUES (%s, %s, %s, TRUE, TRUE, %s)
                """,
                (agent_type, f"test-{agent_type}", f"/tmp/test-{agent_type}.json", model),
            )
            return cur.lastrowid
    finally:
        conn.close()


@pytest.fixture
def mock_claude():
    """Patch TokenClaudeRunner.run to return a successful result + insert primary token."""
    insert_primary_token("claude")
    result = ClaudeResult(
        raw_output="ok",
        input_tokens=1500,
        output_tokens=800,
        cost_usd=0.0123,
        num_turns=3,
        duration_ms=45000,
        subtype="success",
        agent_type="claude",
    )
    with patch("agento.modules.claude.src.runner.TokenClaudeRunner.run", return_value=result):
        yield result




@pytest.fixture
def mock_codex():
    """Patch TokenCodexRunner.run to return a successful result + insert primary token."""
    insert_primary_token("codex", "o3")
    result = ClaudeResult(
        raw_output="Cześć! W czym mogę pomóc?",
        input_tokens=6374,
        output_tokens=None,
        num_turns=1,
        duration_ms=3200,
        subtype="019cbcfa-837a-7130-b776-15ac3d39b1ad",
        agent_type="codex",
        model="o3",
    )
    with patch(
        "agento.modules.codex.src.runner.TokenCodexRunner.run",
        return_value=result,
    ):
        yield result


@pytest.fixture
def jira_todo_fixture() -> dict:
    return _load_fixture("jira_search_todo.json")


@pytest.fixture
def jira_cykliczne_fixture() -> dict:
    return _load_fixture("jira_search_cykliczne.json")


@pytest.fixture
def jira_empty_fixture() -> dict:
    return _load_fixture("jira_search_empty.json")


# ---------------------------------------------------------------------------
# Helpers — each read uses a fresh autocommit connection to avoid
# transaction isolation issues (consumer/publisher commit on separate conns).
# ---------------------------------------------------------------------------

def fetch_job(job_id: int) -> dict | None:
    """Fetch a job row by id (fresh connection, sees latest committed data)."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM job WHERE id = %s", (job_id,))
            return cur.fetchone()
    finally:
        conn.close()


def fetch_all_jobs() -> list[dict]:
    """Fetch all job rows."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM job ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


def fetch_all_schedules() -> list[dict]:
    """Fetch all schedule rows."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM schedule ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


def insert_queued_job(
    *,
    job_type: str = "cron",
    reference_id: str = "AI-1",
    idempotency_key: str = "test:key:1",
    max_attempts: int = 3,
    source: str = "jira",
    context: str | None = None,
) -> int:
    """Insert a TODO job and return its id."""
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job (type, source, reference_id, context,
                                  idempotency_key, status, attempt, max_attempts)
                VALUES (%s, %s, %s, %s, %s, 'TODO', 0, %s)
                """,
                (job_type, source, reference_id, context,
                 idempotency_key, max_attempts),
            )
            return cur.lastrowid
    finally:
        conn.close()


def update_job(job_id: int, **fields) -> None:
    """Update arbitrary fields on a job row."""
    conn = _test_connection(autocommit=True)
    try:
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE job SET {set_clause} WHERE id = %s",
                (*fields.values(), job_id),
            )
    finally:
        conn.close()
