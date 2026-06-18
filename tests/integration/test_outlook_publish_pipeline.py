"""Integration: the Outlook inbound security gate end-to-end against real MySQL + real routing.

The unit tests (tests/unit/modules/outlook/test_channel.py) mock `_resolve_routing` and `publish`, so
they never exercise the real `resolve_agent_view` ("email" ingress binding) nor the real DB write of
`requester_email`. This test closes that gap — it proves the three controlling ACC against a real
`agent_view` + `ingress_identity` + `job` table, which is the closest automated mirror of the live
mailbox→Graph→job behaviour (only the real Graph/DMARC fetch is stubbed).
"""
from __future__ import annotations

import logging

import pytest
import respx
from httpx import Response

from agento.modules.outlook.src.channel import OutlookPublisher
from agento.modules.outlook.src.commands.publish import publish_mail as command_publish_mail

from .conftest import _test_connection, fetch_all_jobs

ALLOWED = ["sklep@mycompanystudio.com", "mklauza@mycompany.com"]


@pytest.fixture
def outlook_route():
    """Create a workspace + agent_view and bind the two allowed senders to it (email ingress).

    workspace/agent_view/ingress_identity are NOT in the autouse truncation set, so this fixture
    cleans up after itself (deleting the workspace cascades to agent_view + ingress_identity).
    """
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO workspace (code, label) VALUES ('ws-outlook-it', 'outlook IT')")
            ws_id = cur.lastrowid
            cur.execute(
                "INSERT INTO agent_view (workspace_id, code, label) VALUES (%s, 'av-outlook-it', 'outlook IT')",
                (ws_id,),
            )
            av_id = cur.lastrowid
            for addr in ALLOWED:
                cur.execute(
                    "INSERT INTO ingress_identity (identity_type, identity_value, agent_view_id) "
                    "VALUES ('email', %s, %s)",
                    (addr, av_id),
                )
        yield av_id
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workspace WHERE code = 'ws-outlook-it'")
        conn.close()


# --------------------------------------------------------------------------- #
# Publisher gate against real DB + real routing
# --------------------------------------------------------------------------- #

def test_acc1_whitelisted_dmarc_pass_publishes_with_requester_email(int_db_config, outlook_route):
    """ACC1: allow-listed sender + DMARC pass → a job row with the From in requester_email, trust=domain."""
    logger = logging.getLogger("it-outlook")
    ok = OutlookPublisher().publish_mail(
        int_db_config, "AAMkAG-real-1",
        sender_email="sklep@mycompanystudio.com", dmarc="pass",
        allowed_senders=ALLOWED, logger=logger,
    )
    assert ok is True
    jobs = fetch_all_jobs()
    assert len(jobs) == 1
    row = jobs[0]
    assert row["source"] == "outlook"
    assert row["reference_id"] == "AAMkAG-real-1"
    assert row["requester_email"] == "sklep@mycompanystudio.com"
    assert row["requester_trust"] == "domain"
    assert row["agent_view_id"] == outlook_route   # routed to the bound agent_view


def test_acc1_operator_self_test_sender_also_publishes(int_db_config, outlook_route):
    """ACC1: the operator's own address (mklauza@mycompany.com) — case-insensitive — also publishes."""
    ok = OutlookPublisher().publish_mail(
        int_db_config, "AAMkAG-real-2",
        sender_email="MKlauza@Mycompany.com", dmarc="pass",
        allowed_senders=ALLOWED, logger=logging.getLogger("it-outlook"),
    )
    assert ok is True
    rows = fetch_all_jobs()
    assert len(rows) == 1
    assert rows[0]["requester_email"] == "mklauza@mycompany.com"  # JobRequester normalises


def test_acc2_non_whitelisted_sender_publishes_nothing(int_db_config, outlook_route, caplog):
    """ACC2: a sender not on allowed_senders creates no job and logs NO security breach."""
    with caplog.at_level(logging.INFO):
        ok = OutlookPublisher().publish_mail(
            int_db_config, "AAMkAG-real-3",
            sender_email="test@mycompanystudio.com", dmarc="pass",
            allowed_senders=ALLOWED, logger=logging.getLogger("it-outlook"),
        )
    assert ok is False
    assert len(fetch_all_jobs()) == 0
    assert "SECURITY_BREACH" not in caplog.text


def test_acc3_whitelisted_dmarc_fail_logs_breach_publishes_nothing(int_db_config, outlook_route, caplog):
    """ACC3: an allow-listed From that fails DMARC is a probable spoof → breach logged, no job."""
    with caplog.at_level(logging.ERROR):
        ok = OutlookPublisher().publish_mail(
            int_db_config, "AAMkAG-spoofed",
            sender_email="sklep@mycompanystudio.com", dmarc="fail",
            allowed_senders=ALLOWED, logger=logging.getLogger("it-outlook"),
        )
    assert ok is False
    assert len(fetch_all_jobs()) == 0
    assert any(r.levelno == logging.ERROR and "SECURITY_BREACH" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Full pipeline through the outlook:publish command (toolbox HTTP stubbed via respx)
# --------------------------------------------------------------------------- #

@respx.mock
def test_full_pipeline_via_command_publishes_only_authorized_dmarc_pass(int_db_config, outlook_route, caplog):
    """outlook:publish → toolbox /api/outlook/unread (stubbed) → client → publisher → real DB.

    Proves the message-shape contract (from.address + dmarc) flows end-to-end and only the
    allow-listed, DMARC-passing message becomes a job; the spoof logs a breach; the stranger is skipped.
    """
    toolbox_url = "http://toolbox:3001"
    respx.post(f"{toolbox_url}/api/outlook/unread").mock(
        return_value=Response(200, json={"messages": [
            {"id": "m-pass", "subject": "ok", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"},
            {"id": "m-stranger", "subject": "nope", "from": {"address": "test@mycompanystudio.com"}, "dmarc": "pass"},
            {"id": "m-spoof", "subject": "spoof", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "fail"},
        ]})
    )
    with caplog.at_level(logging.ERROR):
        count = command_publish_mail(
            int_db_config, toolbox_url, top=10,
            allowed_senders=ALLOWED, logger=logging.getLogger("it-outlook"),
        )
    assert count == 1
    jobs = fetch_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["reference_id"] == "m-pass"
    assert jobs[0]["requester_email"] == "sklep@mycompanystudio.com"
    assert any("SECURITY_BREACH" in r.getMessage() for r in caplog.records)  # the spoof
