"""Integration: Publish idempotency + credential validation (real MySQL)."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch

import pymysql
import pytest

from agento.modules.jira.src.channel import publish_cron, publish_todo

from .conftest import fetch_all_jobs


class TestIdempotency:

    def test_duplicate_cron_publish_rejected(self, int_db_config):
        """Same cron publish within the same minute is rejected (INSERT IGNORE)."""
        logger = logging.getLogger("test")
        now = datetime(2026, 2, 23, 8, 0, 0)

        with patch("agento.modules.jira.src.channel.datetime") as mock_dt:
            mock_dt.now.return_value = now

            first = publish_cron(int_db_config, "AI-3", logger)
            assert first is True

            second = publish_cron(int_db_config, "AI-3", logger)
            assert second is False

        assert len(fetch_all_jobs()) == 1

    def test_different_minute_creates_new_job(self, int_db_config):
        """Cron publish at different minutes creates separate jobs."""
        logger = logging.getLogger("test")

        with patch("agento.modules.jira.src.channel.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 23, 8, 0, 0)
            publish_cron(int_db_config, "AI-3", logger)

            mock_dt.now.return_value = datetime(2026, 2, 23, 8, 1, 0)
            publish_cron(int_db_config, "AI-3", logger)

        assert len(fetch_all_jobs()) == 2

    def test_duplicate_todo_dispatch_rejected_within_hour(self, int_db_config):
        """TODO dispatch is hour-granular — same hour is rejected."""
        logger = logging.getLogger("test")
        now = datetime(2026, 2, 23, 8, 0, 0)

        with patch("agento.modules.jira.src.channel.datetime") as mock_dt:
            mock_dt.now.return_value = now

            first = publish_todo(int_db_config, issue_key=None, logger=logger)
            assert first is True

            second = publish_todo(int_db_config, issue_key=None, logger=logger)
            assert second is False

        assert len(fetch_all_jobs()) == 1


class TestCredentials:

    def test_publish_with_wrong_password_raises(self, int_db_config):
        """Publishing with wrong MySQL credentials raises (not silently swallowed)."""
        bad_config = replace(int_db_config, mysql_password="wrong_password")
        logger = logging.getLogger("test")

        with pytest.raises(pymysql.OperationalError):
            publish_cron(bad_config, "AI-3", logger)
