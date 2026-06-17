from agento.modules.outlook.src.config import OutlookConfig


def test_from_dict_maps_python_fields_and_drops_secrets():
    c = OutlookConfig.from_dict({
        "enabled": True,
        "outlook_tenant_id": "tid",
        "outlook_client_id": "cid",
        "outlook_client_secret": "sec",
        "outlook_cert_path": "/etc/cert.pem",
        "outlook_mailbox_user_id": "agent@example.com",
        "poll_top": 25,
    })
    assert c.enabled is True
    assert c.poll_top == 25
    # Graph secrets/cert/mailbox are toolbox-only — they must NOT become attributes of the Python config.
    assert not hasattr(c, "outlook_client_secret")
    assert not hasattr(c, "outlook_cert_path")
    assert not hasattr(c, "outlook_tenant_id")
    assert not hasattr(c, "outlook_mailbox_user_id")


def test_defaults():
    c = OutlookConfig.from_dict({})
    assert c.enabled is False
    assert c.poll_top == 10
    assert c.require_dmarc is True
    assert c.allowed_senders == ""
    assert c.allowed_senders_list == []


def test_enabled_parses_stringy_falsey_values():
    # DB/ENV give strings — "0"/"false"/"False"/0/False must all disable.
    for v in ("0", "false", "False", 0, False):
        assert OutlookConfig.from_dict({"enabled": v}).enabled is False
    for v in ("1", "true", True):
        assert OutlookConfig.from_dict({"enabled": v}).enabled is True


def test_require_dmarc_parses_stringy_falsey_values():
    # Default-secure: only explicit falsey values turn it off.
    for v in ("0", "false", "False", 0, False):
        assert OutlookConfig.from_dict({"require_dmarc": v}).require_dmarc is False
    for v in ("1", "true", True):
        assert OutlookConfig.from_dict({"require_dmarc": v}).require_dmarc is True


def test_poll_top_is_defensive_and_clamped():
    assert OutlookConfig.from_dict({"poll_top": "999"}).poll_top == 50   # clamp high
    assert OutlookConfig.from_dict({"poll_top": 0}).poll_top == 1        # clamp low
    assert OutlookConfig.from_dict({"poll_top": "abc"}).poll_top == 10   # garbage -> default


def test_allowed_senders_list_normalizes_and_splits():
    c = OutlookConfig.from_dict({"allowed_senders": " Foo@Bar.com , *@Kazar.com ,, "})
    assert c.allowed_senders == " Foo@Bar.com , *@Kazar.com ,, "
    assert c.allowed_senders_list == ["foo@bar.com", "*@kazar.com"]


def test_allowed_senders_list_empty_for_blank():
    assert OutlookConfig.from_dict({"allowed_senders": "   "}).allowed_senders_list == []
    assert OutlookConfig.from_dict({}).allowed_senders_list == []
