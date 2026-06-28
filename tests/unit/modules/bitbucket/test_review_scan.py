"""The heart: watermark + changes-requested detection, all order-independent and force-push safe."""
from agento.modules.bitbucket.src.review_scan import (
    build_changes_key,
    build_comments_key,
    detect_changes_requested,
    flag_unanswered,
    latest_commit_on,
)

AGENT = "{agent-uuid}"
REV = "{reviewer-uuid}"
REV2 = "{reviewer2-uuid}"

T1 = "2026-01-01T10:00:00+00:00"
T2 = "2026-01-01T11:00:00+00:00"
T3 = "2026-01-01T12:00:00+00:00"
T4 = "2026-01-01T13:00:00+00:00"


def _c(author, created_on, *, deleted=False, resolved=False, cid="c1"):
    return {"id": cid, "author_uuid": author, "created_on": created_on, "deleted": deleted, "resolved": resolved}


def _pr(comments=None, commits=None):
    return {"comments": comments or [], "commits": commits or []}


# --- flag_unanswered -------------------------------------------------------------------------------

def test_a_no_comments_no_flag():
    assert flag_unanswered(_pr(), AGENT) == []


def test_b_comment_older_than_watermark_not_flagged():
    pr = _pr(comments=[_c(REV, T1)], commits=[{"date": T3}])
    assert flag_unanswered(pr, AGENT) == []


def test_c_newer_reviewer_comment_is_flagged():
    pr = _pr(comments=[_c(AGENT, T1, cid="a"), _c(REV, T2, cid="r")])
    flagged = flag_unanswered(pr, AGENT)
    assert [c["id"] for c in flagged] == ["r"]


def test_d_agent_own_comment_never_flags():
    pr = _pr(comments=[_c(AGENT, T3, cid="a")])
    assert flag_unanswered(pr, AGENT) == []


def test_e_deleted_comment_ignored():
    pr = _pr(comments=[_c(REV, T3, deleted=True, cid="r")])
    assert flag_unanswered(pr, AGENT) == []


def test_e2_resolved_comment_ignored():
    pr = _pr(comments=[_c(REV, T3, resolved=True, cid="r")])
    assert flag_unanswered(pr, AGENT) == []


def test_f_force_push_advances_watermark_clears_stale_flag():
    # Reviewer commented at T2, but a later commit (T3) means the feedback predates the latest code.
    pr = _pr(comments=[_c(REV, T2, cid="r")], commits=[{"date": T3}])
    assert flag_unanswered(pr, AGENT) == []


def test_g_new_comment_after_push_reflags():
    pr = _pr(comments=[_c(REV, T4, cid="r")], commits=[{"date": T3}])
    assert [c["id"] for c in flag_unanswered(pr, AGENT)] == ["r"]


def test_no_agent_comment_no_commit_flags_all_non_agent():
    pr = _pr(comments=[_c(REV, T1, cid="r1"), _c(REV2, T2, cid="r2")])
    assert {c["id"] for c in flag_unanswered(pr, AGENT)} == {"r1", "r2"}


def test_flag_unanswered_returns_chronological_newest_last():
    pr = _pr(comments=[_c(REV, T3, cid="late"), _c(REV2, T2, cid="early")])
    flagged = flag_unanswered(pr, AGENT)
    assert [c["id"] for c in flagged] == ["early", "late"]


# --- latest_commit_on (R4-2) ----------------------------------------------------------------------

def test_h_latest_commit_on_max_over_unordered_list():
    assert latest_commit_on([{"date": T1}, {"date": T3}, {"date": T2}]) == T3


def test_h_latest_commit_on_oldest_first_list():
    assert latest_commit_on([{"date": T1}, {"date": T2}, {"date": T3}]) == T3


def test_h_latest_commit_on_empty_is_none():
    assert latest_commit_on([]) is None
    assert latest_commit_on(None) is None


# --- detect_changes_requested (R4-3 / F-func3) -----------------------------------------------------

def test_changes_reviewer_event_detected():
    pr = {"changes_requests": [{"user_uuid": REV, "date": T2}]}
    event = detect_changes_requested(pr, AGENT)
    assert event["user_uuid"] == REV


def test_changes_agent_own_event_ignored():
    pr = {"changes_requests": [{"user_uuid": AGENT, "date": T2}]}
    assert detect_changes_requested(pr, AGENT) is None


def test_changes_none_when_empty():
    assert detect_changes_requested({"changes_requests": []}, AGENT) is None
    assert detect_changes_requested({}, AGENT) is None


def test_changes_multiple_reviewers_out_of_order_max_date_wins():
    pr = {"changes_requests": [
        {"user_uuid": REV, "date": T1},
        {"user_uuid": REV2, "date": T4},  # newest, but not first
        {"user_uuid": AGENT, "date": T3},  # agent's own — must be ignored even though newer than REV
        {"user_uuid": REV, "date": T2},
    ]}
    event = detect_changes_requested(pr, AGENT)
    assert event["user_uuid"] == REV2
    assert event["date"] == T4


# --- idempotency keys ------------------------------------------------------------------------------

def test_comments_key_stable_on_noop_and_advances_on_new_feedback():
    ref = "acme/api:42"
    assert build_comments_key(ref, T2) == build_comments_key(ref, T2)
    assert build_comments_key(ref, T2) != build_comments_key(ref, T3)
    assert build_comments_key(ref, T2).startswith("bitbucket:comments:acme/api:42:")


def test_changes_key_deterministic_across_reviewers_advances_on_newer_date():
    ref = "acme/api:42"
    assert build_changes_key(ref, T2) == build_changes_key(ref, T2)
    assert build_changes_key(ref, T2) != build_changes_key(ref, T4)
    assert build_changes_key(ref, T2).startswith("bitbucket:changes:acme/api:42:")
