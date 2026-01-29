from __future__ import annotations

import json
from pathlib import Path

import pytest

from agento.framework.consumer_config import ConsumerConfig
from agento.framework.database_config import DatabaseConfig
from agento.modules.jira.src.config import JiraConfig

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def sample_db_config() -> DatabaseConfig:
    return DatabaseConfig()


@pytest.fixture
def sample_consumer_config() -> ConsumerConfig:
    return ConsumerConfig()


@pytest.fixture
def sample_config() -> JiraConfig:
    return JiraConfig(
        toolbox_url="http://toolbox:3001",
        user="agenty@example.com",
        jira_projects=["AI"],
        jira_status="Cykliczne",
        jira_frequency_field="customfield_10709",
        jira_assignee="",
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


@pytest.fixture
def jira_cykliczne() -> dict:
    return load_fixture("jira_search_cykliczne.json")


@pytest.fixture
def jira_todo() -> dict:
    return load_fixture("jira_search_todo.json")


@pytest.fixture
def jira_empty() -> dict:
    return load_fixture("jira_search_empty.json")


@pytest.fixture
def claude_success() -> dict:
    return load_fixture("claude_output_success.json")
