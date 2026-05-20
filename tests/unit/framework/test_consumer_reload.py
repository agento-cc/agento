"""Tests for Consumer._maybe_reload_bootstrap — per-tick hot-reload."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.consumer import Consumer
from agento.framework.consumer_config import ConsumerConfig
from agento.framework.database_config import DatabaseConfig
from agento.framework.events import ConsumerReloadedEvent


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
             patch("agento.framework.consumer.bootstrap", return_value=[MagicMock(), MagicMock()]) as bs, \
             patch("agento.framework.consumer.dispatch_reload") as dr, \
             patch("agento.framework.consumer.get_event_manager") as gem:
            gc.return_value = MagicMock()
            em = MagicMock()
            gem.return_value = em
            consumer._maybe_reload_bootstrap()
            dr.assert_called_once()
            bs.assert_called_once()
            assert bs.call_args.kwargs.get("quiet") is True
            # consumer_reload_after fires on success with module_count + elapsed_ms
            em.dispatch.assert_called_once()
            event_name, event_obj = em.dispatch.call_args.args
            assert event_name == "consumer_reload_after"
            assert isinstance(event_obj, ConsumerReloadedEvent)
            assert event_obj.module_count == 2
            assert event_obj.elapsed_ms >= 0
            # conn.close() is the only guard against a 5s connection leak
            assert gc.return_value.close.call_count == 1

    def test_skips_when_jobs_active(self, consumer):
        consumer._active_jobs = 1
        with patch("agento.framework.consumer.bootstrap") as bs, \
             patch("agento.framework.consumer.dispatch_reload") as dr, \
             patch("agento.framework.consumer.get_connection") as gc:
            consumer._maybe_reload_bootstrap()
            bs.assert_not_called()
            dr.assert_not_called()
            gc.assert_not_called()

    def test_swallows_bootstrap_failure(self, consumer):
        with patch("agento.framework.consumer.get_connection") as gc, \
             patch("agento.framework.consumer.bootstrap", side_effect=RuntimeError("boom")), \
             patch("agento.framework.consumer.dispatch_reload"), \
             patch("agento.framework.consumer.get_event_manager") as gem:
            gc.return_value = MagicMock()
            em = MagicMock()
            gem.return_value = em
            consumer._maybe_reload_bootstrap()  # must not raise
            # consumer_reload_after must NOT fire when bootstrap raises
            em.dispatch.assert_not_called()
            # conn.close() still runs from the finally block
            assert gc.return_value.close.call_count == 1

    def test_swallows_db_failure(self, consumer):
        with patch("agento.framework.consumer.get_connection", side_effect=Exception("db down")), \
             patch("agento.framework.consumer.bootstrap") as bs, \
             patch("agento.framework.consumer.get_event_manager") as gem:
            em = MagicMock()
            gem.return_value = em
            consumer._maybe_reload_bootstrap()
            bs.assert_not_called()
            em.dispatch.assert_not_called()

    def test_db_error_log_does_not_include_message(self, consumer):
        """Credentials may appear in PyMySQL OperationalError messages — only the class name is logged."""
        with patch("agento.framework.consumer.get_connection", side_effect=Exception("pass=hunter2")):
            consumer._maybe_reload_bootstrap()
            warn_calls = consumer.logger.warning.call_args_list
            assert any("Exception" in str(c) for c in warn_calls)
            assert not any("hunter2" in str(c) for c in warn_calls)
