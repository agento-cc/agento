"""Integration: the Outlook per-agent_view publisher loop against real MySQL + real config resolution.

Unit tests mock the framework helpers; this proves the loop fans each mailbox's messages to the
correct agent_view, honours per-view allowed_senders/DMARC, and dedupes a shared mailbox — against
real agent_view + core_config_data + job rows (only the toolbox Graph fetch is stubbed via respx).
"""
from __future__ import annotations

import json
import logging

import pytest
import respx
from httpx import Response

from agento.framework.scoped_config import Scope, scoped_config_set
from agento.modules.outlook.src.commands.publish import publish_all_views

from .conftest import _test_connection, fetch_all_jobs

ALLOWED = "sklep@mycompanystudio.com, mklauza@mycompany.com"
TOOLBOX_URL = "http://toolbox:3001"


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


def _unread_stub(by_view):
    """Return a respx side_effect that maps the posted agent_view_id -> {mailbox, messages}."""
    def _handler(request):
        agent_view_id = json.loads(request.content)["agent_view_id"]
        return Response(200, json=by_view[agent_view_id])
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
    respx.post(f"{TOOLBOX_URL}/api/outlook/unread").mock(side_effect=_unread_stub(by_view))

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
    respx.post(f"{TOOLBOX_URL}/api/outlook/unread").mock(side_effect=_unread_stub(by_view))

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
    respx.post(f"{TOOLBOX_URL}/api/outlook/unread").mock(
        side_effect=_unread_stub({dev_id: shared, ops_id: shared})
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
