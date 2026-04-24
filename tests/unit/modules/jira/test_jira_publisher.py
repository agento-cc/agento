from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from agento.framework.job_models import AgentType
from agento.modules.jira.src.channel import build_idempotency_key, publish_cron, publish_todo


class TestIdempotencyKey:
    @patch("agento.modules.jira.src.channel.datetime")
    def test_idempotency_key_cron(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        key = build_idempotency_key(AgentType.CRON, "AI-123")
        assert key == "jira:cron:AI-123:20260220_0800"

    @patch("agento.modules.jira.src.channel.datetime")
    def test_idempotency_key_todo_with_issue(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        key = build_idempotency_key(AgentType.TODO, "AI-456")
        assert key == "jira:todo:AI-456:20260220_0800"

    @patch("agento.modules.jira.src.channel.datetime")
    def test_idempotency_key_todo_dispatch(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        key = build_idempotency_key(AgentType.TODO, None)
        assert key == "jira:todo:dispatch:20260220_0800"

    @patch("agento.modules.jira.src.channel.datetime")
    def test_idempotency_key_same_minute_is_stable(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 15)
        key1 = build_idempotency_key(AgentType.CRON, "AI-1")
        key2 = build_idempotency_key(AgentType.CRON, "AI-1")
        assert key1 == key2

    @patch("agento.modules.jira.src.channel.datetime")
    def test_idempotency_key_different_minute_differs(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        key1 = build_idempotency_key(AgentType.CRON, "AI-1")
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 1)
        key2 = build_idempotency_key(AgentType.CRON, "AI-1")
        assert key1 != key2


class TestIdempotencyKeyWithUpdated:
    """Tests for build_idempotency_key with the updated parameter (TDD for the dup-skip fix)."""

    @patch("agento.modules.jira.src.channel.datetime")
    def test_todo_with_updated_includes_update_minute_in_key(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        key = build_idempotency_key(AgentType.TODO, "AI-6", updated="2026-02-24T16:45:00.000+0000")
        assert key == "jira:todo:AI-6:u20260224_1645"

    @patch("agento.modules.jira.src.channel.datetime")
    def test_todo_same_hour_different_updated_yields_different_keys(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        key_before = build_idempotency_key(AgentType.TODO, "AI-6", updated="2026-02-24T16:30:00.000+0000")
        key_after = build_idempotency_key(AgentType.TODO, "AI-6", updated="2026-02-24T16:45:00.000+0000")
        assert key_before != key_after

    @patch("agento.modules.jira.src.channel.datetime")
    def test_todo_without_updated_uses_minute_bucket(self, mock_dt):
        """Fallback: publish_todo without updated uses per-minute bucket."""
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        key = build_idempotency_key(AgentType.TODO, "AI-6")
        assert key == "jira:todo:AI-6:20260224_1647"

    @patch("agento.modules.jira.src.channel.datetime")
    def test_todo_updated_none_equals_no_updated(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        key_no_arg = build_idempotency_key(AgentType.TODO, "AI-6")
        key_none = build_idempotency_key(AgentType.TODO, "AI-6", updated=None)
        assert key_no_arg == key_none

    @patch("agento.modules.jira.src.channel.datetime")
    def test_cron_ignores_updated_parameter(self, mock_dt):
        """updated has no effect on CRON keys (they are already minute-granular)."""
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        key_without = build_idempotency_key(AgentType.CRON, "AI-6")
        key_with = build_idempotency_key(AgentType.CRON, "AI-6", updated="2026-02-24T16:45:00.000+0000")
        assert key_without == key_with


class TestPublishCron:
    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.datetime")
    def test_publish_cron_calls_generic_publish(self, mock_dt, mock_publish, sample_config):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        mock_publish.return_value = True

        result = publish_cron(sample_config, "AI-123")

        assert result is True
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][1] == AgentType.CRON
        assert call_args[0][2] == "jira"  # source
        assert call_args[1]["reference_id"] == "AI-123"


class TestPublishTodo:
    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.datetime")
    def test_publish_todo_dispatch(self, mock_dt, mock_publish, sample_config):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        mock_publish.return_value = True

        result = publish_todo(sample_config, None)

        assert result is True
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][1] == AgentType.TODO
        assert call_args[1]["reference_id"] is None

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.datetime")
    def test_publish_todo_specific_issue(self, mock_dt, mock_publish, sample_config):
        mock_dt.now.return_value = datetime(2026, 2, 20, 8, 0)
        mock_publish.return_value = True

        result = publish_todo(sample_config, "AI-789")

        assert result is True
        call_args = mock_publish.call_args
        assert call_args[1]["reference_id"] == "AI-789"

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.datetime")
    def test_publish_todo_with_updated_passes_it_to_key(self, mock_dt, mock_publish, sample_config):
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        mock_publish.return_value = True

        publish_todo(sample_config, "AI-6", updated="2026-02-24T16:45:00.000+0000")

        call_args = mock_publish.call_args
        idempotency_key = call_args[0][3]
        assert idempotency_key == "jira:todo:AI-6:u20260224_1645"

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.datetime")
    def test_publish_todo_updated_same_issue_same_hour_different_key(self, mock_dt, mock_publish, sample_config):
        """Simulate the exact bug: updated issue in same hour must NOT be a duplicate."""
        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 5)
        mock_publish.return_value = True
        publish_todo(sample_config, "AI-6", updated="2026-02-24T16:00:00.000+0000")
        key_first = mock_publish.call_args[0][3]

        mock_dt.now.return_value = datetime(2026, 2, 24, 16, 47)
        mock_publish.return_value = False  # DB would return False for a real dup
        publish_todo(sample_config, "AI-6", updated="2026-02-24T16:45:00.000+0000")
        key_second = mock_publish.call_args[0][3]

        assert key_first != key_second

    @patch("agento.modules.jira.src.channel.publish")
    def test_publish_todo_requests_skip_if_active(self, mock_publish, sample_config):
        """publish_todo must guard against in-flight duplicates (e.g. Jira
        search-index lag re-publishing the same ticket while a job is running)."""
        mock_publish.return_value = True

        publish_todo(sample_config, "AI-64", updated="2026-02-24T16:45:00.000+0000")

        assert mock_publish.call_args.kwargs.get("skip_if_active") is True
