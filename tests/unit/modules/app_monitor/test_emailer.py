from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.modules.app_monitor.src.emailer import SmtpConfig, send_alert


def _cfg(**overrides) -> SmtpConfig:
    defaults = dict(
        host="smtp.example.com", port=587, user="u", password="p",
        from_addr="agento@example.com", tls=True,
    )
    defaults.update(overrides)
    return SmtpConfig(**defaults)


@patch("agento.modules.app_monitor.src.emailer.smtplib.SMTP")
def test_send_alert_uses_tls_and_login(mock_smtp_cls):
    smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp

    send_alert(_cfg(tls=True), "ops@example.com", "S", "B")

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    smtp.send_message.assert_called_once()
    msg = smtp.send_message.call_args.args[0]
    assert msg["From"] == "agento@example.com"
    assert msg["To"] == "ops@example.com"
    assert msg["Subject"] == "S"
    assert msg.get_content().strip() == "B"


@patch("agento.modules.app_monitor.src.emailer.smtplib.SMTP")
def test_send_alert_no_tls_no_user(mock_smtp_cls):
    smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = smtp

    send_alert(_cfg(tls=False, user="", password=""), "ops@example.com", "S", "B")

    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
    smtp.send_message.assert_called_once()


@patch("agento.modules.app_monitor.src.emailer.smtplib.SMTP")
def test_send_alert_propagates_smtp_failure(mock_smtp_cls):
    smtp = MagicMock()
    smtp.send_message.side_effect = OSError("boom")
    mock_smtp_cls.return_value.__enter__.return_value = smtp

    with pytest.raises(OSError, match="boom"):
        send_alert(_cfg(), "ops@example.com", "S", "B")
