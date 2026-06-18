from unittest.mock import MagicMock, patch

import pytest

from agento.modules.outlook.src.commands.publish import publish_mail

WHITELIST = ["sklep@mycompanystudio.com"]


@patch("agento.modules.outlook.src.commands.publish.OutlookPublisher")
@patch("agento.modules.outlook.src.commands.publish.OutlookToolboxClient")
def test_publishes_each_unread(MockClient, MockPub):
    client = MockClient.return_value
    client.list_unread.return_value = [
        {"id": "m1", "subject": "A", "from": {"address": "a@b.com"}, "dmarc": "pass"},
        {"id": "m2", "subject": "B", "from": {"address": "c@d.com"}, "dmarc": "pass"},
    ]
    pub = MockPub.return_value
    pub.publish_mail.return_value = True
    logger = MagicMock()

    count = publish_mail(
        db_config=object(), toolbox_url="http://tb:3001", top=10,
        allowed_senders=WHITELIST, logger=logger,
    )

    assert count == 2
    assert pub.publish_mail.call_count == 2
    client.close.assert_called_once()


@patch("agento.modules.outlook.src.commands.publish.OutlookPublisher")
@patch("agento.modules.outlook.src.commands.publish.OutlookToolboxClient")
def test_threads_sender_dmarc_and_gate_config(MockClient, MockPub):
    client = MockClient.return_value
    client.list_unread.return_value = [
        {"id": "m1", "from": {"address": "Sklep@Mycompanystudio.com"}, "dmarc": "pass"},
    ]
    pub = MockPub.return_value
    pub.publish_mail.return_value = True

    publish_mail(
        db_config=object(), toolbox_url="http://tb:3001", top=5,
        allowed_senders=WHITELIST, logger=MagicMock(),
    )

    _, kwargs = pub.publish_mail.call_args
    assert kwargs["sender_email"] == "Sklep@Mycompanystudio.com"
    assert kwargs["dmarc"] == "pass"
    assert kwargs["allowed_senders"] == WHITELIST


@patch("agento.modules.outlook.src.commands.publish.OutlookPublisher")
@patch("agento.modules.outlook.src.commands.publish.OutlookToolboxClient")
def test_error_on_one_message_does_not_stop_loop(MockClient, MockPub):
    client = MockClient.return_value
    client.list_unread.return_value = [{"id": "ok"}, {"id": "bad"}, {"id": "ok2"}]
    pub = MockPub.return_value
    pub.publish_mail.side_effect = [True, RuntimeError("db down"), True]
    logger = MagicMock()

    count = publish_mail(
        db_config=object(), toolbox_url="http://tb:3001", top=10,
        allowed_senders=WHITELIST, logger=logger,
    )

    assert count == 2
    assert pub.publish_mail.call_count == 3
    logger.exception.assert_called_once()
    client.close.assert_called_once()


@patch("agento.modules.outlook.src.commands.publish.OutlookPublisher")
@patch("agento.modules.outlook.src.commands.publish.OutlookToolboxClient")
def test_skips_messages_without_id(MockClient, MockPub):
    client = MockClient.return_value
    client.list_unread.return_value = [{"subject": "no id"}, {"id": "m2"}]
    pub = MockPub.return_value
    pub.publish_mail.return_value = True

    count = publish_mail(
        db_config=object(), toolbox_url="http://tb:3001", top=10,
        allowed_senders=WHITELIST, logger=MagicMock(),
    )

    assert count == 1
    assert pub.publish_mail.call_count == 1


@patch("agento.modules.outlook.src.commands.publish.OutlookPublisher")
@patch("agento.modules.outlook.src.commands.publish.OutlookToolboxClient")
def test_client_closed_even_when_list_unread_raises(MockClient, MockPub):
    client = MockClient.return_value
    client.list_unread.side_effect = RuntimeError("toolbox down")
    logger = MagicMock()

    with pytest.raises(RuntimeError):
        publish_mail(
            db_config=object(), toolbox_url="http://tb:3001", top=10,
            allowed_senders=WHITELIST, logger=logger,
        )

    client.close.assert_called_once()
