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
    assert OutlookPublisher().build_idempotency_key("m-123") == "outlook:mail:m-123"


def test_idempotency_key_fits_db_column_for_realistic_graph_id():
    graph_id = "AAMkAG" + "A" * 170
    key = OutlookPublisher().build_idempotency_key(graph_id)
    assert len(key) <= 255
    assert len(graph_id) <= 255


# ---- ACC1: whitelisted + dmarc=pass -> publishes to the SUPPLIED agent_view_id/priority ----

def test_acc1_publishes_with_supplied_view_and_priority_and_domain_trust():
    p = OutlookPublisher()
    with patch("agento.modules.outlook.src.channel.publish", return_value=True) as mock_publish:
        result = p.publish_mail(
            object(), "m1", agent_view_id=7, priority=60,
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


def test_acc1_wildcard_pattern_matches():
    p = OutlookPublisher()
    with patch("agento.modules.outlook.src.channel.publish", return_value=True) as mock_publish:
        result = p.publish_mail(
            object(), "m3", agent_view_id=1, priority=50,
            sender_email="anyone@partner.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=MagicMock(),
        )
    assert result is True
    mock_publish.assert_called_once()


def test_wildcard_does_not_cross_at_sign():
    p = OutlookPublisher()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "m4", agent_view_id=1,
            sender_email="evil@sub.partner.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=MagicMock(),
        )
    assert result is False
    mock_publish.assert_not_called()


# ---- ACC2: non-whitelisted -> NO publish, NO breach log ----

def test_acc2_non_whitelisted_sender_skipped_no_breach():
    p = OutlookPublisher()
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        result = p.publish_mail(
            object(), "m5", agent_view_id=1,
            sender_email="test@mycompanystudio.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=logger,
        )
    assert result is False
    mock_publish.assert_not_called()
    for call in logger.error.call_args_list:
        assert "SECURITY_BREACH" not in str(call)
    logger.info.assert_called()


def test_acc2_does_not_leak_full_address_only_domain():
    p = OutlookPublisher()
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish"):
        p.publish_mail(
            object(), "m5b", agent_view_id=1,
            sender_email="secret-user@mycompanystudio.com", dmarc="pass",
            allowed_senders=WHITELIST, logger=logger,
        )
    blob = " ".join(str(c) for c in logger.info.call_args_list)
    assert "secret-user" not in blob


# ---- ACC3: whitelisted + dmarc!=pass -> NO publish AND SECURITY_BREACH logged ----

def test_acc3_whitelisted_sender_dmarc_fail_logs_breach_dispatches_event_no_publish():
    p = OutlookPublisher()
    logger = MagicMock()
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish, \
         patch("agento.modules.outlook.src.channel.get_event_manager") as mock_em:
        result = p.publish_mail(
            object(), "AAMkAG-spoofed-message-id", agent_view_id=1,
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
    # a probable spoof also dispatches the framework security_breach event (ops alert)
    mock_em.return_value.dispatch.assert_called_once()
    evt_name, evt = mock_em.return_value.dispatch.call_args.args
    assert evt_name == "security_breach_after"
    assert evt.channel == "outlook"
    assert evt.reason == "dmarc_not_pass"
    assert evt.sender == "sklep@mycompanystudio.com"


def test_acc3_quarantine_and_reject_are_breaches():
    p = OutlookPublisher()
    for verdict in ("quarantine", "reject"):
        logger = MagicMock()
        with patch("agento.modules.outlook.src.channel.publish") as mock_publish, \
             patch("agento.modules.outlook.src.channel.get_event_manager") as mock_em:
            result = p.publish_mail(
                object(), "m-spoof", agent_view_id=1,
                sender_email="sklep@mycompanystudio.com", dmarc=verdict,
                allowed_senders=WHITELIST, logger=logger,
            )
        assert result is False
        mock_publish.assert_not_called()
        logger.error.assert_called_once()
        mock_em.return_value.dispatch.assert_called_once()


def test_dmarc_none_or_bestguesspass_is_not_a_breach_no_publish_no_event():
    # A recordless domain (none / bestguesspass / missing verdict) is NOT a spoof: info log, no
    # SECURITY_BREACH error, no ops event, and still not published (fail-closed).
    p = OutlookPublisher()
    for verdict in (None, "none", "bestguesspass", "temperror"):
        logger = MagicMock()
        with patch("agento.modules.outlook.src.channel.publish") as mock_publish, \
             patch("agento.modules.outlook.src.channel.get_event_manager") as mock_em:
            result = p.publish_mail(
                object(), "m6", agent_view_id=1,
                sender_email="sklep@mycompanystudio.com", dmarc=verdict,
                allowed_senders=WHITELIST, logger=logger,
            )
        assert result is False
        mock_publish.assert_not_called()
        for call in logger.error.call_args_list:
            assert "SECURITY_BREACH" not in str(call)
        mock_em.return_value.dispatch.assert_not_called()
        logger.info.assert_called()


def test_empty_allowed_senders_blocks_everyone():
    p = OutlookPublisher()
    logger = MagicMock()
    for allowed in (None, [], ""):
        with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
            result = p.publish_mail(
                object(), "m8", agent_view_id=1,
                sender_email="sklep@mycompanystudio.com", dmarc="pass",
                allowed_senders=allowed, logger=logger,
            )
        assert result is False
        mock_publish.assert_not_called()
    for call in logger.error.call_args_list:
        assert "SECURITY_BREACH" not in str(call)


# ---- Publisher protocol shim threads agent_view_id + priority + gate kwargs ----

def test_publish_todo_shim_threads_view_priority_and_gate_kwargs():
    p = OutlookPublisher()
    captured = {}

    def _spy(db_config, message_id, **kwargs):
        captured["message_id"] = message_id
        captured.update(kwargs)
        return True

    p.publish_mail = _spy  # type: ignore[assignment]
    result = p.publish_todo(
        object(), reference_id="m10",
        agent_view_id=3, priority=70,
        sender_email="sklep@mycompanystudio.com", dmarc="pass",
        allowed_senders=WHITELIST, logger=logging.getLogger("t"),
    )
    assert result is True
    assert captured["message_id"] == "m10"
    assert captured["agent_view_id"] == 3
    assert captured["priority"] == 70
    assert captured["sender_email"] == "sklep@mycompanystudio.com"
    assert captured["dmarc"] == "pass"
    assert captured["allowed_senders"] == WHITELIST


# ---- S2: allow-list patterns escape every regex metachar (no fail-OPEN widening) ----

def test_question_mark_in_allowed_pattern_is_literal_not_quantifier():
    # '?' must be escaped, not treated as a regex 'optional' quantifier — otherwise pattern
    # "a?b@x.com" would also admit "b@x.com" (a WIDENING of the allow-list, the fail-OPEN direction).
    p = OutlookPublisher()
    patterns = ["a?b@x.com"]
    # the literal address still matches the literal pattern
    with patch("agento.modules.outlook.src.channel.publish", return_value=True):
        assert p.publish_mail(
            object(), "mq1", agent_view_id=1, sender_email="a?b@x.com",
            dmarc="pass", allowed_senders=patterns, logger=MagicMock(),
        ) is True
    # but the quantifier-widened address must NOT match
    with patch("agento.modules.outlook.src.channel.publish") as mock_publish:
        assert p.publish_mail(
            object(), "mq2", agent_view_id=1, sender_email="b@x.com",
            dmarc="pass", allowed_senders=patterns, logger=MagicMock(),
        ) is False
        mock_publish.assert_not_called()
