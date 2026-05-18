"""Thin SMTP wrapper for app_monitor's alert observer.

Kept dependency-free (stdlib only) so it remains trivially mockable in tests.
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    from_addr: str
    tls: bool


def send_alert(cfg: SmtpConfig, to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on any SMTP failure."""
    msg = EmailMessage()
    msg["From"] = cfg.from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(cfg.host, cfg.port) as smtp:
        if cfg.tls:
            smtp.starttls()
        if cfg.user:
            smtp.login(cfg.user, cfg.password)
        smtp.send_message(msg)
