from __future__ import annotations

from unittest.mock import MagicMock, patch

from agento.framework.agent_manager.config import AgentManagerConfig
from agento.framework.agent_manager.models import AgentProvider, RotationResult
from agento.framework.agent_manager.rotator import rotate_all, rotate_tokens, select_best_token

from .conftest import make_token, make_usage


class TestSelectBestToken:
    def test_returns_none_for_empty_list(self):
        assert select_best_token([], {}) is None

    def test_picks_token_with_most_remaining(self):
        t1 = make_token(id=1, token_limit=100_000)
        t2 = make_token(id=2, token_limit=100_000)
        usage_map = {
            1: make_usage(1, total_tokens=80_000, call_count=10),
            2: make_usage(2, total_tokens=20_000, call_count=5),
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # 80k remaining vs 20k remaining

    def test_unlimited_token_preferred(self):
        t1 = make_token(id=1, token_limit=100_000)
        t2 = make_token(id=2, token_limit=0)  # unlimited
        usage_map = {
            1: make_usage(1, total_tokens=0, call_count=0),
            2: make_usage(2, total_tokens=500_000, call_count=100),
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # unlimited always wins

    def test_tiebreak_by_fewer_calls(self):
        t1 = make_token(id=1, token_limit=100_000)
        t2 = make_token(id=2, token_limit=100_000)
        usage_map = {
            1: make_usage(1, total_tokens=50_000, call_count=10),
            2: make_usage(2, total_tokens=50_000, call_count=5),
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # same remaining, but fewer calls

    def test_no_usage_data_means_zero_used(self):
        t1 = make_token(id=1, token_limit=100_000)
        t2 = make_token(id=2, token_limit=100_000)
        usage_map = {
            1: make_usage(1, total_tokens=50_000, call_count=5),
            # token 2 has no usage entry
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # 100k remaining (no usage) vs 50k

    def test_single_token(self):
        t1 = make_token(id=1)

        best = select_best_token([t1], {})

        assert best.id == 1

    def test_all_overdrawn_picks_least_overdrawn(self):
        t1 = make_token(id=1, token_limit=100_000)
        t2 = make_token(id=2, token_limit=100_000)
        usage_map = {
            1: make_usage(1, total_tokens=150_000),  # -50k
            2: make_usage(2, total_tokens=120_000),  # -20k
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # -20k is less overdrawn than -50k

    def test_primary_token_always_wins(self):
        t1 = make_token(id=1, token_limit=100_000, is_primary=False)
        t2 = make_token(id=2, token_limit=100_000, is_primary=True)
        usage_map = {
            1: make_usage(1, total_tokens=0, call_count=0),  # 100k remaining
            2: make_usage(2, total_tokens=90_000, call_count=50),  # only 10k remaining
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # primary wins despite less capacity

    def test_no_primary_falls_back_to_capacity(self):
        t1 = make_token(id=1, token_limit=100_000, is_primary=False)
        t2 = make_token(id=2, token_limit=100_000, is_primary=False)
        usage_map = {
            1: make_usage(1, total_tokens=80_000),
            2: make_usage(2, total_tokens=20_000),
        }

        best = select_best_token([t1, t2], usage_map)

        assert best.id == 2  # more remaining capacity


class TestRotateTokens:
    @patch("agento.framework.agent_manager.rotator.update_active_token")
    @patch("agento.framework.agent_manager.rotator.get_usage_summaries")
    @patch("agento.framework.agent_manager.rotator.get_token_by_path")
    @patch("agento.framework.agent_manager.rotator.resolve_active_token")
    @patch("agento.framework.agent_manager.rotator.list_tokens")
    def test_initial_rotation(self, mock_list, mock_resolve, mock_get_by_path, mock_usage, mock_update):
        config = AgentManagerConfig()
        t1 = make_token(id=1)
        mock_list.return_value = [t1]
        mock_resolve.return_value = None  # no active token yet
        mock_usage.return_value = []

        result = rotate_tokens(MagicMock(), config, AgentProvider.CLAUDE)

        assert result is not None
        assert result.reason == "initial"
        assert result.previous_token_id is None
        assert result.new_token_id == 1
        mock_update.assert_called_once()

    @patch("agento.framework.agent_manager.rotator.update_active_token")
    @patch("agento.framework.agent_manager.rotator.get_usage_summaries")
    @patch("agento.framework.agent_manager.rotator.get_token_by_path")
    @patch("agento.framework.agent_manager.rotator.resolve_active_token")
    @patch("agento.framework.agent_manager.rotator.list_tokens")
    def test_rotation_to_better_token(self, mock_list, mock_resolve, mock_get_by_path, mock_usage, mock_update):
        config = AgentManagerConfig()
        t1 = make_token(id=1, credentials_path="/etc/tokens/c1.json")
        t2 = make_token(id=2, credentials_path="/etc/tokens/c2.json")
        mock_list.return_value = [t1, t2]
        mock_resolve.return_value = "/etc/tokens/c1.json"
        mock_get_by_path.return_value = t1
        mock_usage.return_value = [
            make_usage(1, total_tokens=90_000),
            make_usage(2, total_tokens=10_000),
        ]

        result = rotate_tokens(MagicMock(), config, AgentProvider.CLAUDE)

        assert result.reason == "rotation"
        assert result.previous_token_id == 1
        assert result.new_token_id == 2
        mock_update.assert_called_once()

    @patch("agento.framework.agent_manager.rotator.update_active_token")
    @patch("agento.framework.agent_manager.rotator.get_usage_summaries")
    @patch("agento.framework.agent_manager.rotator.get_token_by_path")
    @patch("agento.framework.agent_manager.rotator.resolve_active_token")
    @patch("agento.framework.agent_manager.rotator.list_tokens")
    def test_unchanged_when_best_is_current(self, mock_list, mock_resolve, mock_get_by_path, mock_usage, mock_update):
        config = AgentManagerConfig()
        t1 = make_token(id=1, credentials_path="/etc/tokens/c1.json")
        mock_list.return_value = [t1]
        mock_resolve.return_value = "/etc/tokens/c1.json"
        mock_get_by_path.return_value = t1
        mock_usage.return_value = [make_usage(1, total_tokens=10_000)]

        result = rotate_tokens(MagicMock(), config, AgentProvider.CLAUDE)

        assert result.reason == "unchanged"
        assert result.previous_token_id == 1
        assert result.new_token_id == 1
        mock_update.assert_not_called()

    @patch("agento.framework.agent_manager.rotator.list_tokens")
    def test_returns_none_when_no_tokens(self, mock_list):
        config = AgentManagerConfig()
        mock_list.return_value = []

        result = rotate_tokens(MagicMock(), config, AgentProvider.CLAUDE)

        assert result is None


class TestRotateAll:
    @patch("agento.framework.agent_manager.rotator.rotate_tokens")
    def test_iterates_all_providers(self, mock_rotate):
        config = AgentManagerConfig()
        mock_rotate.return_value = MagicMock(spec=RotationResult)

        results = rotate_all(MagicMock(), config)

        assert mock_rotate.call_count == len(AgentProvider)
        assert len(results) == len(AgentProvider)

    @patch("agento.framework.agent_manager.rotator.rotate_tokens")
    def test_skips_none_results(self, mock_rotate):
        config = AgentManagerConfig()
        mock_rotate.side_effect = [None, MagicMock(spec=RotationResult)]

        results = rotate_all(MagicMock(), config)

        assert len(results) == 1
