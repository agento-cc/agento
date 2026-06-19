from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

from agento.modules.outlook.src.commands.publish import publish_all_views
from agento.modules.outlook.src.config import OutlookConfig

P = "agento.modules.outlook.src.commands.publish"


def _views(*specs):
    # specs: (id, code)
    return [SimpleNamespace(id=i, code=c) for (i, c) in specs]


def _cfg(enabled=True, poll_top=10, allowed="sklep@x.com"):
    return OutlookConfig(enabled=enabled, poll_top=poll_top, allowed_senders=allowed)


class _FakeScoped:
    """Stand-in for ScopedConfigService: returns configs[scope_id]."""
    configs: ClassVar[dict] = {}

    def __init__(self, conn, scope, scope_id):
        self._scope_id = scope_id

    def get_module(self, name):
        return _FakeScoped.configs.get(self._scope_id)


def _patch_env(configs, list_unread_side_effect):
    _FakeScoped.configs = configs
    client = MagicMock()
    client.list_unread.side_effect = list_unread_side_effect
    pub = MagicMock()
    pub.publish_mail.return_value = True
    return client, pub


@patch(f"{P}.resolve_publish_priority", side_effect=lambda conn, av_id: 50 + av_id)
@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_multi_view_fans_each_mailbox_to_its_own_view(MockClient, MockPub, mock_gaav, mock_prio):
    mock_gaav.return_value = _views((1, "dev"), (2, "ops"))
    responses = {
        1: {"mailbox": "dev@x.com", "messages": [{"id": "d1", "from": {"address": "sklep@x.com"}, "dmarc": "pass"}]},
        2: {"mailbox": "ops@x.com", "messages": [{"id": "o1", "from": {"address": "sklep@x.com"}, "dmarc": "pass"}]},
    }
    client, pub = _patch_env({1: _cfg(), 2: _cfg()},
                             lambda top, *, agent_view_id: responses[agent_view_id])
    MockClient.return_value = client
    MockPub.return_value = pub

    count = publish_all_views(object(), MagicMock(), "http://tb:3001", MagicMock())

    assert count == 2
    by_view = {c.kwargs["agent_view_id"]: c.args[1] for c in pub.publish_mail.call_args_list}
    assert by_view == {1: "d1", 2: "o1"}
    prios = {c.kwargs["agent_view_id"]: c.kwargs["priority"] for c in pub.publish_mail.call_args_list}
    assert prios == {1: 51, 2: 52}
    client.close.assert_called_once()


@patch(f"{P}.resolve_publish_priority", side_effect=lambda conn, av_id: 50)
@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_disabled_view_is_skipped_and_not_polled(MockClient, MockPub, mock_gaav, mock_prio):
    mock_gaav.return_value = _views((1, "dev"), (2, "ops"))
    client, pub = _patch_env({1: _cfg(enabled=False), 2: _cfg(enabled=True)},
                             lambda top, *, agent_view_id: {"mailbox": "ops@x.com", "messages": []})
    MockClient.return_value = client
    MockPub.return_value = pub

    publish_all_views(object(), MagicMock(), "http://tb:3001", MagicMock())

    polled = [c.kwargs["agent_view_id"] for c in client.list_unread.call_args_list]
    assert polled == [2]


@patch(f"{P}.resolve_publish_priority", side_effect=lambda conn, av_id: 50)
@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_per_view_poll_top_and_allowed_senders_honored(MockClient, MockPub, mock_gaav, mock_prio):
    mock_gaav.return_value = _views((1, "dev"))
    client, pub = _patch_env({1: _cfg(poll_top=25, allowed="a@x.com, b@y.com")},
                             lambda top, *, agent_view_id: {"mailbox": "dev@x.com",
                                                            "messages": [{"id": "d1", "from": {"address": "a@x.com"}, "dmarc": "pass"}]})
    MockClient.return_value = client
    MockPub.return_value = pub

    publish_all_views(object(), MagicMock(), "http://tb:3001", MagicMock())

    assert client.list_unread.call_args.kwargs["top"] == 25
    assert pub.publish_mail.call_args.kwargs["allowed_senders"] == ["a@x.com", "b@y.com"]


@patch(f"{P}.resolve_publish_priority", side_effect=lambda conn, av_id: 50)
@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_shared_mailbox_deduped_lowest_id_wins_with_warning(MockClient, MockPub, mock_gaav, mock_prio):
    mock_gaav.return_value = _views((1, "dev"), (2, "ops"))
    shared = {"mailbox": "shared@x.com", "messages": [{"id": "s1", "from": {"address": "sklep@x.com"}, "dmarc": "pass"}]}
    client, pub = _patch_env({1: _cfg(), 2: _cfg()},
                             lambda top, *, agent_view_id: shared)
    MockClient.return_value = client
    MockPub.return_value = pub
    logger = MagicMock()

    count = publish_all_views(object(), MagicMock(), "http://tb:3001", logger)

    assert count == 1
    assert pub.publish_mail.call_count == 1
    assert pub.publish_mail.call_args.kwargs["agent_view_id"] == 1
    assert any("shared@x.com" in str(c) for c in logger.warning.call_args_list)


@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_unconfigured_mailbox_is_skipped(MockClient, MockPub, mock_gaav):
    mock_gaav.return_value = _views((1, "dev"))
    client, pub = _patch_env({1: _cfg()},
                             lambda top, *, agent_view_id: {"mailbox": None, "messages": [{"id": "x"}]})
    MockClient.return_value = client
    MockPub.return_value = pub

    count = publish_all_views(object(), MagicMock(), "http://tb:3001", MagicMock())

    assert count == 0
    pub.publish_mail.assert_not_called()


@patch(f"{P}.get_active_agent_views", return_value=[])
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_no_active_views_is_a_clean_noop(MockClient, MockPub, mock_gaav):
    client = MagicMock()
    MockClient.return_value = client
    count = publish_all_views(object(), MagicMock(), "http://tb:3001", MagicMock())
    assert count == 0
    MockPub.return_value.publish_mail.assert_not_called()
    client.close.assert_called_once()


@patch(f"{P}.resolve_publish_priority", side_effect=lambda conn, av_id: 50)
@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_per_view_error_logs_and_continues(MockClient, MockPub, mock_gaav, mock_prio):
    mock_gaav.return_value = _views((1, "dev"), (2, "ops"))

    def side(top, *, agent_view_id):
        if agent_view_id == 1:
            raise RuntimeError("toolbox down for view 1")
        return {"mailbox": "ops@x.com", "messages": [{"id": "o1", "from": {"address": "sklep@x.com"}, "dmarc": "pass"}]}

    client, pub = _patch_env({1: _cfg(), 2: _cfg()}, side)
    MockClient.return_value = client
    MockPub.return_value = pub
    logger = MagicMock()

    count = publish_all_views(object(), MagicMock(), "http://tb:3001", logger)

    assert count == 1
    logger.exception.assert_called()
    client.close.assert_called_once()


@patch(f"{P}.resolve_publish_priority", side_effect=lambda conn, av_id: 50)
@patch(f"{P}.ScopedConfigService", _FakeScoped)
@patch(f"{P}.get_active_agent_views")
@patch(f"{P}.OutlookPublisher")
@patch(f"{P}.OutlookToolboxClient")
def test_agent_view_code_filter_runs_one_view_only(MockClient, MockPub, mock_gaav, mock_prio):
    mock_gaav.return_value = _views((1, "dev"), (2, "ops"))
    client, pub = _patch_env({1: _cfg(), 2: _cfg()},
                             lambda top, *, agent_view_id: {"mailbox": f"v{agent_view_id}@x.com",
                                                            "messages": [{"id": "m", "from": {"address": "sklep@x.com"}, "dmarc": "pass"}]})
    MockClient.return_value = client
    MockPub.return_value = pub

    publish_all_views(object(), MagicMock(), "http://tb:3001", MagicMock(), agent_view_code="ops")

    polled = [c.kwargs["agent_view_id"] for c in client.list_unread.call_args_list]
    assert polled == [2]
