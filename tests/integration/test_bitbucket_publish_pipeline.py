"""Integration: the Bitbucket publish pipeline end-to-end against real MySQL + real scoped config.

The unit tests mock the toolbox client + framework publish; this closes the gap by running run_lane
against a real ``agent_view`` + ``core_config_data`` + ``job`` table, with only the toolbox HTTP
(``/api/bitbucket/open-prs``) stubbed via respx. It proves the controlling ACC: right job rows per lane,
idempotency, lane independence (distinct source), the empty-allow-list skip, and the multi-view
DEFAULT-scope fan-out guard.
"""
from __future__ import annotations

import logging

import pytest
import respx
from httpx import Response

from agento.framework.scoped_config import Scope, scoped_config_set
from agento.modules.bitbucket.src.commands._loop import run_lane

from .conftest import _test_connection, fetch_all_jobs

TOOLBOX_URL = "http://toolbox:3001"
AGENT = "{agent-uuid}"
REV = "{reviewer-uuid}"
T2 = "2026-01-01T11:00:00+00:00"
T3 = "2026-01-01T12:00:00+00:00"
T4 = "2026-01-01T13:00:00+00:00"

logger = logging.getLogger("it-bitbucket")


def _set_cfg(cur_conn, scope, scope_id, **values):
    for key, val in values.items():
        scoped_config_set(cur_conn, f"bitbucket/{key}", val, scope=scope, scope_id=scope_id)


@pytest.fixture
def bitbucket_env():
    """Create workspaces/agent_views + scoped bitbucket config; clean up (cascade + config rows)."""
    conn = _test_connection(autocommit=True)
    created = {}

    def make_view(ws_code, av_code, *, scope=Scope.AGENT_VIEW, **cfg):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO workspace (code, label) VALUES (%s, %s)", (ws_code, ws_code))
            ws_id = cur.lastrowid
            cur.execute(
                "INSERT INTO agent_view (workspace_id, code, label) VALUES (%s, %s, %s)",
                (ws_id, av_code, av_code),
            )
            av_id = cur.lastrowid
        scope_id = av_id if scope == Scope.AGENT_VIEW else 0
        _set_cfg(conn, scope, scope_id, **cfg)
        created.setdefault("ws", []).append(ws_code)
        return av_id

    try:
        yield make_view
    finally:
        with conn.cursor() as cur:
            for ws_code in created.get("ws", []):
                cur.execute("DELETE FROM workspace WHERE code = %s", (ws_code,))
            cur.execute("DELETE FROM core_config_data WHERE path LIKE 'bitbucket/%%'")
        conn.close()


def _comments_pr(comment_time=T3):
    return {
        "workspace": "acme", "repo": "api", "id": 42, "title": "Add X", "updated_on": T3,
        "comments": [{"id": "r1", "author_uuid": REV, "created_on": comment_time, "deleted": False, "resolved": False}],
        "commits": [],
    }


def _changes_pr(date=T2):
    return {
        "workspace": "acme", "repo": "api", "id": 42, "title": "Add X", "updated_on": T3,
        "changes_requests": [{"user_uuid": REV, "date": date}],
    }


# --------------------------------------------------------------------------- #

@respx.mock
def test_comments_lane_writes_job_with_requester(int_db_config, bitbucket_env):
    bitbucket_env("ws-bb-1", "av-bb-1", enabled="1", bitbucket_workspace="acme",
                  bitbucket_account_uuid=AGENT, repo_allowlist="api")
    respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs").mock(
        return_value=Response(200, json={"pull_requests": [_comments_pr()], "errors": []})
    )
    conn = _test_connection(autocommit=True)
    try:
        published = run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments")
    finally:
        conn.close()
    assert published == 1
    jobs = fetch_all_jobs()
    assert len(jobs) == 1
    row = jobs[0]
    assert row["source"] == "bitbucket-comments"
    assert row["reference_id"] == "acme/api:42"
    assert row["requester_key"] == f"bitbucket:account:{REV}"
    assert row["requester_trust"] == "account"
    assert row["priority"] == 50


@respx.mock
def test_changes_lane_writes_prioritized_job(int_db_config, bitbucket_env):
    bitbucket_env("ws-bb-2", "av-bb-2", enabled="1", bitbucket_workspace="acme",
                  bitbucket_account_uuid=AGENT, repo_allowlist="api")
    respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs").mock(
        return_value=Response(200, json={"pull_requests": [_changes_pr()], "errors": []})
    )
    conn = _test_connection(autocommit=True)
    try:
        published = run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="changes")
    finally:
        conn.close()
    assert published == 1
    jobs = fetch_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["source"] == "bitbucket-changes"
    assert jobs[0]["priority"] == 80  # base 50 + bump 30


@respx.mock
def test_rerun_identical_data_queues_nothing(int_db_config, bitbucket_env):
    bitbucket_env("ws-bb-3", "av-bb-3", enabled="1", bitbucket_workspace="acme",
                  bitbucket_account_uuid=AGENT, repo_allowlist="api")
    respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs").mock(
        return_value=Response(200, json={"pull_requests": [_comments_pr()], "errors": []})
    )
    conn = _test_connection(autocommit=True)
    try:
        assert run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments") == 1
        # Second pass, identical data: idempotency key stable + job still active ⇒ nothing new.
        assert run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments") == 0
    finally:
        conn.close()
    assert len(fetch_all_jobs()) == 1


@respx.mock
def test_new_feedback_after_completion_queues_new_job(int_db_config, bitbucket_env):
    bitbucket_env("ws-bb-4", "av-bb-4", enabled="1", bitbucket_workspace="acme",
                  bitbucket_account_uuid=AGENT, repo_allowlist="api")
    route = respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs")
    route.mock(return_value=Response(200, json={"pull_requests": [_comments_pr(T3)], "errors": []}))
    conn = _test_connection(autocommit=True)
    try:
        assert run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments") == 1
        # Mark the first job terminal so it is no longer "active".
        with conn.cursor() as cur:
            cur.execute("UPDATE job SET status = 'SUCCESS' WHERE source = 'bitbucket-comments'")
        # A genuinely newer comment ⇒ a new idempotency key ⇒ a new job.
        route.mock(return_value=Response(200, json={"pull_requests": [_comments_pr(T4)], "errors": []}))
        assert run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments") == 1
    finally:
        conn.close()
    assert len(fetch_all_jobs()) == 2


@respx.mock
def test_fast_lane_not_blocked_by_active_sweep_job(int_db_config, bitbucket_env):
    av_id = bitbucket_env("ws-bb-5", "av-bb-5", enabled="1", bitbucket_workspace="acme",
                          bitbucket_account_uuid=AGENT, repo_allowlist="api")
    # An active sweep-lane (bitbucket-comments) job already exists for this PR.
    seed = _test_connection(autocommit=True)
    try:
        with seed.cursor() as cur:
            cur.execute(
                "INSERT INTO job (type, source, agent_view_id, reference_id, idempotency_key, status, "
                "attempt, max_attempts) VALUES ('todo','bitbucket-comments',%s,'acme/api:42',"
                "'bitbucket:comments:acme/api:42:seed','RUNNING',0,3)",
                (av_id,),
            )
    finally:
        seed.close()
    respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs").mock(
        return_value=Response(200, json={"pull_requests": [_changes_pr()], "errors": []})
    )
    conn = _test_connection(autocommit=True)
    try:
        published = run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="changes")
    finally:
        conn.close()
    assert published == 1  # distinct source ⇒ skip_if_active does not collide with the sweep job
    sources = sorted(j["source"] for j in fetch_all_jobs())
    assert sources == ["bitbucket-changes", "bitbucket-comments"]


@respx.mock
def test_empty_allowlist_view_produces_no_jobs(int_db_config, bitbucket_env):
    bitbucket_env("ws-bb-6", "av-bb-6", enabled="1", bitbucket_workspace="acme",
                  bitbucket_account_uuid=AGENT, repo_allowlist="")
    route = respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs").mock(
        return_value=Response(200, json={"pull_requests": [_comments_pr()], "errors": []})
    )
    conn = _test_connection(autocommit=True)
    try:
        published = run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments")
    finally:
        conn.close()
    assert published == 0
    assert len(fetch_all_jobs()) == 0
    assert not route.called  # empty allow-list ⇒ the toolbox is never even called


@respx.mock
def test_multiview_default_scope_no_fanout(int_db_config, bitbucket_env):
    # R4-1: two active views, config only at DEFAULT scope (no per-view identity) ⇒ both skipped ⇒ the
    # shared PR is published at most once (here: zero — no view qualifies).
    bitbucket_env("ws-bb-7a", "av-bb-7a", scope=Scope.DEFAULT, enabled="1", bitbucket_workspace="acme",
                  bitbucket_account_uuid=AGENT, repo_allowlist="api")
    bitbucket_env("ws-bb-7b", "av-bb-7b")  # second active view, no own config
    route = respx.post(f"{TOOLBOX_URL}/api/bitbucket/open-prs").mock(
        return_value=Response(200, json={"pull_requests": [_comments_pr()], "errors": []})
    )
    conn = _test_connection(autocommit=True)
    try:
        published = run_lane(int_db_config, conn, TOOLBOX_URL, logger, lane="comments")
    finally:
        conn.close()
    assert published == 0
    assert len(fetch_all_jobs()) == 0
    assert not route.called
