"""Tests for Consumer._maybe_reload_bootstrap — per-tick hot-reload."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.consumer import Consumer
from agento.framework.consumer_config import ConsumerConfig
from agento.framework.database_config import DatabaseConfig


@pytest.fixture
def consumer():
    db_config = DatabaseConfig(
        mysql_host="h",
        mysql_port=3306,
        mysql_user="u",
        mysql_password="p",
        mysql_database="d",
    )
    cc = ConsumerConfig(max_workers=1, poll_interval=5.0)
    return Consumer(db_config, cc, logger=MagicMock())


class TestMaybeReloadBootstrap:
    def test_reloads_when_idle(self, consumer):
        with patch("agento.framework.consumer.get_connection") as gc, \
             patch("agento.framework.consumer.bootstrap") as bs, \
             patch("agento.framework.consumer.dispatch_shutdown") as ds:
            gc.return_value = MagicMock()
            consumer._maybe_reload_bootstrap()
            ds.assert_called_once()
            bs.assert_called_once()
            assert bs.call_args.kwargs.get("quiet") is True

    def test_skips_when_jobs_active(self, consumer):
        consumer._active_jobs = 1
        with patch("agento.framework.consumer.bootstrap") as bs, \
             patch("agento.framework.consumer.dispatch_shutdown") as ds, \
             patch("agento.framework.consumer.get_connection") as gc:
            consumer._maybe_reload_bootstrap()
            bs.assert_not_called()
            ds.assert_not_called()
            gc.assert_not_called()

    def test_swallows_bootstrap_failure(self, consumer):
        with patch("agento.framework.consumer.get_connection") as gc, \
             patch("agento.framework.consumer.bootstrap", side_effect=RuntimeError("boom")), \
             patch("agento.framework.consumer.dispatch_shutdown"):
            gc.return_value = MagicMock()
            consumer._maybe_reload_bootstrap()  # must not raise

    def test_swallows_db_failure(self, consumer):
        with patch("agento.framework.consumer.get_connection", side_effect=Exception("db down")), \
             patch("agento.framework.consumer.bootstrap") as bs:
            consumer._maybe_reload_bootstrap()
            bs.assert_not_called()

    def test_db_error_log_does_not_include_message(self, consumer):
        """Credentials may appear in PyMySQL OperationalError messages — only the class name is logged."""
        with patch("agento.framework.consumer.get_connection", side_effect=Exception("pass=hunter2")):
            consumer._maybe_reload_bootstrap()
            warn_calls = consumer.logger.warning.call_args_list
            assert any("Exception" in str(c) for c in warn_calls)
            assert not any("hunter2" in str(c) for c in warn_calls)
