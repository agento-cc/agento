import logging
from unittest.mock import MagicMock, patch

from agento.framework.channels.base import Channel, PromptFragments
from agento.framework.job_models import RequesterTrust
from agento.modules.outlook.src.channel import OutlookChannel, OutlookPublisher

WHITELIST = ["sklep@mycompanystudio.com", "mklauza@mycompany.com", "*@partner.com"]


def test_channel_protocol_and_name():
    ch = OutlookChannel()
    assert isinstance(ch, Channel)
    assert ch.name == "outlook"


def test_prompt_fragments_reference_tools_and_id():
    f = OutlookChannel().get_prompt_fragments("AAMkAG=")
    assert isinstance(f, PromptFragments)
    assert "outlook_get_message" in f.read_context
    assert "AAMkAG=" in f.read_context
    assert "outlook_reply" in f.respond
    assert "outlook_mark_processed" in f.transition_done


def test_followup_fragments_carry_instructions():
    f = OutlookChannel().get_followup_fragments("AAMkAG=", "sprawdź raport")
    assert "sprawdź raport" in f.extra
    assert "outlook_get_message" in f.read_context


def test_idempotency_key_is_stable_per_message():
    p = OutlookPublisher()
    assert p.build_idempotency_key("m-123") == "outlook:mail:m-123"


def test_idempotency_key_fits_db_column_for_realistic_graph_id():
    graph_id = "AAMkAG" + "A" * 170  # 176 chars — longer than typical, still must fit
    key = OutlookPublisher().build_idempotency_key(graph_id)
    assert len(key) <= 255
    assert len(graph_id) <= 255  # reference_id stores the raw id; it must fit too


def _routed(view_id=7, priority=60):
    def _fn(*a, **k):
        return (view_id, priority)
    return _fn


# ---- ACC1: whitelisted sender + dmarc=pass -> publishes, requester.email + trust=DOMAIN ----

def test_acc1_whitelisted_sender_dmarc_pass_publishes_with_domain_trust(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    with patch("agento.modules.outlook.src.channel.publish", return_value=True) as mock_publish:
        result = p.publish_mail(
            object(), "m1",
            sender_email="sklep@mycompanystudio.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=MagicMock(),
        )
    assert result is True
    mock_publish.assert_called_once()
    _, kwargs = mock_publish.call_args
    assert kwargs["agent_view_id"] == 7
    assert kwargs["priority"] == 60
    assert kwargs["skip_if_active"] is True
    requester = kwargs["requester"]
    assert requester.email == "sklep@mycompanystudio.com"
    assert requester.trust == RequesterTrust.DOMAIN
    assert requester.key.startswith("outlook:email:")
    assert requester.meta == {"basis": "email_from", "dmarc": "pass"}


def test_acc1_second_whitelisted_sender_also_publishes(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    with patch("agento.modules.outlook.src.channel.publish", return_value=True) as mock_publish:
        result = p.publish_mail(
            object(), "m2",
            sender_email="MKlauza@Mycompany.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=MagicMock(),
        )
    assert result is True
    mock_publish.assert_called_once()


def test_acc1_wildcard_pattern_matches(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    with patch("agento.modules.outlook.src.channel.publish", return_value=True) as mock_publish:
        result = p.publish_mail(
            object(), "m3",
            sender_email="anyone@partner.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=MagicMock(),
        )
    assert result is True
    mock_publish.assert_called_once()


def test_wildcard_does_not_cross_at_sign(monkeypatch):
    # `*@partner.com` must NOT match `evil@sub.partner.com` (anchored, [^@]* semantics).
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "m4",
            sender_email="evil@sub.partner.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=logger,
        )
    assert result is False
    mock_publish.assert_not_called()


# ---- ACC2: non-whitelisted sender -> NO publish, NO breach log ----

def test_acc2_non_whitelisted_sender_skipped_no_breach(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "m5",
            sender_email="test@mycompanystudio.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=logger,
        )
    assert result is False
    mock_publish.assert_not_called()
    # No SECURITY_BREACH error logged for an ordinary non-whitelisted sender.
    for call in logger.error.call_args_list:
        assert "SECURITY_BREACH" not in str(call)
    logger.info.assert_called()


def test_acc2_does_not_leak_full_address_only_domain(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish"):
        p.publish_mail(
            object(), "m5b",
            sender_email="secret-user@mycompanystudio.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=logger,
        )
    # info log must carry the domain but never the local part of a non-authorized address.
    blob = " ".join(str(c) for c in logger.info.call_args_list)
    assert "secret-user" not in blob


# ---- ACC3: whitelisted sender + dmarc=fail -> NO publish AND SECURITY_BREACH logged ----

def test_acc3_whitelisted_sender_dmarc_fail_logs_breach_no_publish(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "AAMkAG-spoofed-message-id",
            sender_email="sklep@mycompanystudio.com", dmarc="fail",
            allowed_senders=WHITELIST, logger=logger,
        )
    assert result is False
    mock_publish.assert_not_called()
    logger.error.assert_called_once()
    args, kwargs = logger.error.call_args
    assert "SECURITY_BREACH" in args[0]
    extra = kwargs["extra"]
    assert extra["event"] == "security_breach"
    assert extra["reason"] == "dmarc_not_pass"
    assert extra["sender"] == "sklep@mycompanystudio.com"
    assert extra["dmarc"] == "fail"
    assert "message_id" in extra


def test_acc3_whitelisted_sender_dmarc_none_logs_breach(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "m6",
            sender_email="sklep@mycompanystudio.com", dmarc=None,
            allowed_senders=WHITELIST, logger=logger,
        )
    assert result is False
    mock_publish.assert_not_called()
    logger.error.assert_called_once()


# ---- fail-closed: empty allowed_senders blocks everyone ----

def test_empty_allowed_senders_blocks_everyone(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", _routed())
    logger = MagicMock()
    for allowed in (None, [], ""):
        with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
            result = p.publish_mail(
                object(), "m8",
                sender_email="sklep@mycompanystudio.com", dmarc="pass",
                allowed_senders=allowed, logger=logger,
            )
        assert result is False
        mock_publish.assert_not_called()
    # fail-closed is ordinary non-routing, not a breach
    for call in logger.error.call_args_list:
        assert "SECURITY_BREACH" not in str(call)


# ---- routing gate: authorized + dmarc pass but unrouted -> skip, no publish ----

def test_authorized_dmarc_pass_but_unrouted_skips(monkeypatch):
    p = OutlookPublisher()
    monkeypatch.setattr(p, "_resolve_routing", lambda *a, **k: (None, 50))
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "m9",
            sender_email="sklep@mycompanystudio.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=logger,
        )
    assert result is False
    mock_publish.assert_not_called()
    logger.warning.assert_called()


# ---- Publisher protocol shim threads the gate kwargs through ----

def test_publish_todo_shim_threads_gate_kwargs(monkeypatch):
    p = OutlookPublisher()
    captured = {}

    def _spy(db_config, message_id, **kwargs):
        captured["message_id"] = message_id
        captured.update(kwargs)
        return True

    monkeypatch.setattr(p, "publish_mail", _spy)
    result = p.publish_todo(
        object(), reference_id="m10",
        sender_email="sklep@mycompanystudio.com", dmarc="pass",
        allowed_senders=WHITELIST,
        logger=logging.getLogger("t"),
    )
    assert result is True
    assert captured["message_id"] == "m10"
    assert captured["sender_email"] == "sklep@mycompanystudio.com"
    assert captured["dmarc"] == "pass"
    assert captured["allowed_senders"] == WHITELIST
