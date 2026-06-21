"""Integration: the Outlook per-agent_view publisher loop against real MySQL + real config resolution.

Unit tests mock the framework helpers; this proves the loop fans each mailbox's messages to the
correct agent_view, honours per-view allowed_senders/DMARC, dedupes a shared mailbox, and persists
the per-mailbox delta cursor — against real agent_view + core_config_data + job + outlook_poll_cursor
rows (only the toolbox Graph fetch is stubbed via respx).
"""
from __future__ import annotations

import json
import logging

import pytest
import respx
from httpx import Response

from agento.framework.scoped_config import Scope, scoped_config_set
from agento.modules.outlook.src.commands.publish import publish_all_views
from agento.modules.outlook.src.cursor import load_cursors

from .conftest import _test_connection, fetch_all_jobs

ALLOWED = "sklep@mycompanystudio.com, mklauza@mycompany.com"
TOOLBOX_URL = "http://toolbox:3001"
DELTA_URL = f"{TOOLBOX_URL}/api/outlook/delta"


@pytest.fixture(autouse=True)
def _clean_cursors():
    conn = _test_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM outlook_poll_cursor")
        yield
        with conn.cursor() as cur:
            cur.execute("DELETE FROM outlook_poll_cursor")
    finally:
        conn.close()


@pytest.fixture
def two_views():
    """Create one workspace + two active agent_views, each with scoped outlook config (enabled +
    allowed_senders). Returns (dev_id, ops_id). Cleans up workspace (cascades to agent_view) and the
    agent_view-scoped core_config_data rows it wrote — none are in the autouse truncation set."""
    conn = _test_connection(autocommit=True)
    av_ids = []
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO workspace (code, label) VALUES ('ws-outlook-pv', 'outlook pv')")
            ws_id = cur.lastrowid
            for code in ("av-outlook-dev", "av-outlook-ops"):
                cur.execute(
                    "INSERT INTO agent_view (workspace_id, code, label) VALUES (%s, %s, %s)",
                    (ws_id, code, code),
                )
                av_ids.append(cur.lastrowid)
        for av_id in av_ids:
            scoped_config_set(conn, "outlook/enabled", "1", scope=Scope.AGENT_VIEW, scope_id=av_id)
            scoped_config_set(conn, "outlook/allowed_senders", ALLOWED, scope=Scope.AGENT_VIEW, scope_id=av_id)
        conn.commit()
        yield av_ids[0], av_ids[1]
    finally:
        with conn.cursor() as cur:
            for av_id in av_ids:
                cur.execute(
                    "DELETE FROM core_config_data WHERE scope = 'agent_view' AND scope_id = %s",
                    (av_id,),
                )
            cur.execute("DELETE FROM workspace WHERE code = 'ws-outlook-pv'")
        conn.close()


def _delta_stub(by_view, *, delta_link="L-NEXT"):
    """Return a respx side_effect that maps the posted agent_view_id -> {mailbox, messages, deltaLink}."""
    def _handler(request):
        payload = json.loads(request.content)
        out = dict(by_view[payload["agent_view_id"]])
        out.setdefault("deltaLink", delta_link)
        out.setdefault("resynced", False)
        return Response(200, json=out)
    return _handler


@respx.mock
def test_multi_view_fans_each_mailbox_to_correct_view(int_db_config, two_views):
    dev_id, ops_id = two_views
    by_view = {
        dev_id: {"mailbox": "dev@example.com", "messages": [
            {"id": "m-dev", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}]},
        ops_id: {"mailbox": "ops@example.com", "messages": [
            {"id": "m-ops", "from": {"address": "mklauza@mycompany.com"}, "dmarc": "pass"}]},
    }
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        count = publish_all_views(int_db_config, conn, TOOLBOX_URL, logging.getLogger("it-outlook"))
    finally:
        conn.close()

    assert count == 2
    jobs = {j["reference_id"]: j for j in fetch_all_jobs()}
    assert jobs["m-dev"]["agent_view_id"] == dev_id
    assert jobs["m-dev"]["requester_email"] == "sklep@mycompanystudio.com"
    assert jobs["m-dev"]["requester_trust"] == "domain"
    assert jobs["m-ops"]["agent_view_id"] == ops_id


@respx.mock
def test_spoof_and_stranger_blocked_per_view(int_db_config, two_views, caplog):
    dev_id, ops_id = two_views
    by_view = {
        dev_id: {"mailbox": "dev@example.com", "messages": [
            {"id": "m-pass", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"},
            {"id": "m-stranger", "from": {"address": "stranger@elsewhere.com"}, "dmarc": "pass"},
            {"id": "m-spoof", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "fail"},
        ]},
        ops_id: {"mailbox": "ops@example.com", "messages": []},
    }
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        with caplog.at_level(logging.ERROR):
            count = publish_all_views(int_db_config, conn, TOOLBOX_URL, logging.getLogger("it-outlook"))
    finally:
        conn.close()

    assert count == 1
    jobs = fetch_all_jobs()
    assert [j["reference_id"] for j in jobs] == ["m-pass"]
    assert any("SECURITY_BREACH" in r.getMessage() for r in caplog.records)


@respx.mock
def test_shared_mailbox_deduped_lowest_id_wins(int_db_config, two_views):
    dev_id, ops_id = two_views  # dev_id < ops_id (insertion order)
    shared = {"mailbox": "shared@example.com", "messages": [
        {"id": "m-shared", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}]}
    respx.post(DELTA_URL).mock(
        side_effect=_delta_stub({dev_id: shared, ops_id: shared})
    )

    conn = _test_connection(autocommit=False)
    try:
        count = publish_all_views(int_db_config, conn, TOOLBOX_URL, logging.getLogger("it-outlook"))
    finally:
        conn.close()

    assert count == 1
    jobs = fetch_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["agent_view_id"] == dev_id  # lowest id wins


@respx.mock
def test_junk_starvation_gone_valid_mail_published_behind_junk(int_db_config, two_views):
    """ACC: >= poll_top non-allow-listed unread, OLDER than one allow-listed DMARC-pass mail. The delta
    handler pages the whole set (no fixed-window truncation) so the valid mail publishes."""
    dev_id, _ = two_views
    junk = [{"id": f"junk-{i}", "from": {"address": f"spam{i}@nowhere.com"}, "dmarc": "pass"} for i in range(15)]
    valid = {"id": "valid-1", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}
    by_view = {dev_id: {"mailbox": "dev@example.com", "messages": [*junk, valid]}}  # valid is LAST (newest)
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        count = publish_all_views(int_db_config, conn, TOOLBOX_URL,
                                  logging.getLogger("it-outlook"), agent_view_code="av-outlook-dev")
    finally:
        conn.close()
    assert count == 1
    assert [j["reference_id"] for j in fetch_all_jobs()] == ["valid-1"]


@respx.mock
def test_in_flight_published_but_unread_do_not_block_new_valid_mail(int_db_config, two_views):
    """ACC: >= poll_top already-published-but-still-unread messages must not block a newer valid one."""
    dev_id, _ = two_views
    inflight = [{"id": f"wip-{i}", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"} for i in range(12)]
    new_valid = {"id": "new-valid", "from": {"address": "mklauza@mycompany.com"}, "dmarc": "pass"}
    by_view = {dev_id: {"mailbox": "dev@example.com", "messages": [*inflight, new_valid]}}
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        publish_all_views(int_db_config, conn, TOOLBOX_URL,
                          logging.getLogger("it-outlook"), agent_view_code="av-outlook-dev")
    finally:
        conn.close()
    refs = {j["reference_id"] for j in fetch_all_jobs()}
    assert "new-valid" in refs  # the newer valid mail was reached, not starved


@respx.mock
def test_cursor_written_only_after_publish_keyed_by_mailbox(int_db_config, two_views):
    """ACC: outlook_poll_cursor is written, keyed by normalized mailbox UPN, only after publishing."""
    dev_id, _ = two_views
    link = "https://graph.microsoft.com/v1.0/users/dev@example.com/mailFolders/Inbox/messages/delta?$deltatoken=ABC"
    by_view = {dev_id: {"mailbox": "DEV@Example.com", "deltaLink": link,
                        "messages": [{"id": "c1", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}]}}
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        publish_all_views(int_db_config, conn, TOOLBOX_URL,
                          logging.getLogger("it-outlook"), agent_view_code="av-outlook-dev")
    finally:
        conn.close()

    rconn = _test_connection(autocommit=False)
    try:
        assert load_cursors(rconn) == {"dev@example.com": link}  # normalized key, full deltaLink persisted
    finally:
        rconn.close()


@respx.mock
def test_long_message_id_round_trips_untruncated(int_db_config, two_views):
    """Regression for migration 027: a >255-char Graph id + 'outlook:mail:' prefix must persist
    untruncated. On the old VARCHAR(255) column, INSERT IGNORE under strict sql_mode silently
    truncated it, colliding distinct emails and dropping the second as a phantom duplicate."""
    dev_id, _ = two_views
    long_id = "AAMk" + "B" * 260  # 264 chars, well over 255
    by_view = {dev_id: {"mailbox": "dev@example.com", "messages": [
        {"id": long_id, "subject": "Long id test",
         "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}]}}
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        count = publish_all_views(int_db_config, conn, TOOLBOX_URL,
                                  logging.getLogger("it-outlook"), agent_view_code="av-outlook-dev")
    finally:
        conn.close()

    assert count == 1
    job = fetch_all_jobs()[0]
    assert job["idempotency_key"] == f"outlook:mail:{long_id}"  # full key, no truncation
    assert job["reference_id"].rsplit("::", 1)[-1] == long_id    # message_id survives at the tail


@respx.mock
def test_subject_becomes_readable_compound_reference_id(int_db_config, two_views):
    """A polled subject becomes a slug prefix on reference_id (readable in logs/admin) while the
    bare message_id stays recoverable at the tail and the idempotency_key stays bare."""
    dev_id, _ = two_views
    by_view = {dev_id: {"mailbox": "dev@example.com", "messages": [
        {"id": "AAMkXYZ", "subject": "Zażółć: Raport & wnioski",
         "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}]}}
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    conn = _test_connection(autocommit=False)
    try:
        publish_all_views(int_db_config, conn, TOOLBOX_URL,
                          logging.getLogger("it-outlook"), agent_view_code="av-outlook-dev")
    finally:
        conn.close()

    job = fetch_all_jobs()[0]
    assert job["reference_id"] == "zazolc-raport-wnioski::AAMkXYZ"
    assert job["reference_id"].rsplit("::", 1)[-1] == "AAMkXYZ"
    assert job["idempotency_key"] == "outlook:mail:AAMkXYZ"  # bare, dedup keys on message_id only


@respx.mock
def test_replay_same_delta_creates_no_duplicate_jobs(int_db_config, two_views):
    """ACC: resync / held-cursor replays must not duplicate jobs (idempotency_key holds)."""
    dev_id, _ = two_views
    by_view = {dev_id: {"mailbox": "dev@example.com", "deltaLink": "L1",
                        "messages": [{"id": "dup-1", "from": {"address": "sklep@mycompanystudio.com"}, "dmarc": "pass"}]}}
    respx.post(DELTA_URL).mock(side_effect=_delta_stub(by_view))

    for _ in range(2):  # poll twice with the SAME message id
        conn = _test_connection(autocommit=False)
        try:
            publish_all_views(int_db_config, conn, TOOLBOX_URL,
                              logging.getLogger("it-outlook"), agent_view_code="av-outlook-dev")
        finally:
            conn.close()

    assert len([j for j in fetch_all_jobs() if j["reference_id"] == "dup-1"]) == 1
