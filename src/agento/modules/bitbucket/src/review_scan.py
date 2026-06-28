"""Pure PR-review scan logic — no I/O, unit-tested in isolation.

The toolbox returns a normalized per-PR record (see toolbox/api-handlers.js); these functions decide,
from that record alone, whether a PR has work for a given lane. Everything is computed client-side by
``max(date)`` / timestamp-filter so the result never depends on the order the Bitbucket API happened to
return collections in (the v2 collection endpoints expose no guaranteed sort — R4-2 / R4-3).
"""
from __future__ import annotations

from datetime import datetime


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a Bitbucket ISO-8601 timestamp to an aware datetime, or None.

    Bitbucket emits ``2026-01-02T03:04:05.123456+00:00`` (and sometimes a ``Z`` suffix). We parse to a
    real datetime rather than compare strings so mixed offsets/precisions still order correctly.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def latest_commit_on(commits: list[dict] | None) -> str | None:
    """Newest commit timestamp = ``max(commit.date)`` over a bounded commits window.

    Order-independent (the commits endpoint exposes no ``sort`` and may return oldest-first), and an
    empty/absent list ⇒ ``None`` (e.g. the source branch was deleted), so the caller's watermark then
    falls back to the agent's last comment (R4-2). ``commits`` is a list of ``{"date": iso}`` dicts.
    """
    if not commits:
        return None
    best_raw: str | None = None
    best_dt: datetime | None = None
    for c in commits:
        raw = c.get("date") if isinstance(c, dict) else None
        dt = _parse_iso(raw)
        if dt is None:
            continue
        if best_dt is None or dt > best_dt:
            best_dt, best_raw = dt, raw
    return best_raw


def flag_unanswered(pr: dict, account_uuid: str) -> list[dict]:
    """Return the non-agent comments that are newer than the watermark (chronological order).

    "Unanswered" = a non-deleted, non-resolved comment authored by someone other than the agent whose
    ``created_on`` is newer than BOTH the agent's last comment AND the PR's last commit (a timestamp
    watermark — survives force-push). A resolved thread counts as addressed (F-func2). ``created_on`` is
    immutable on edit, so it is the correct watermark field. Returns ``[]`` when nothing is outstanding.
    """
    comments = pr.get("comments") or []

    agent_times = [
        dt
        for c in comments
        if c.get("author_uuid") == account_uuid and not c.get("deleted")
        if (dt := _parse_iso(c.get("created_on"))) is not None
    ]
    agent_last = max(agent_times) if agent_times else None
    last_commit = _parse_iso(latest_commit_on(pr.get("commits")))
    watermark = _latest(agent_last, last_commit)

    unanswered = []
    for c in comments:
        if c.get("deleted") or c.get("resolved"):
            continue
        if c.get("author_uuid") == account_uuid:
            continue
        created = _parse_iso(c.get("created_on"))
        if created is None:
            continue
        if watermark is None or created > watermark:
            unanswered.append(c)

    unanswered.sort(key=lambda c: _parse_iso(c.get("created_on")) or datetime.min)
    return unanswered


def detect_changes_requested(pr: dict, account_uuid: str) -> dict | None:
    """Return the newest non-agent ``changes_request`` event, or None.

    ``pr["changes_requests"]`` is the UNORDERED set of ``changes_request`` events from the PR's
    ``/activity`` log (the toolbox already drops the agent's own — see api-handlers.js). We pick the one
    with ``max(date)`` rather than the first entry, so multiple reviewers / out-of-order events resolve
    deterministically to the latest changes-request (R4-3).
    """
    events = [
        e
        for e in (pr.get("changes_requests") or [])
        if e.get("user_uuid") != account_uuid and _parse_iso(e.get("date")) is not None
    ]
    if not events:
        return None
    return max(events, key=lambda e: _parse_iso(e.get("date")))


def build_comments_key(reference_id: str, newest_unanswered_created_on: str) -> str:
    """Idempotency key for the comments lane.

    Carries the newest unanswered comment's ``created_on`` so a no-op rescan dedupes (stable key) while
    genuinely new feedback produces a new key and re-queues.
    """
    return f"bitbucket:comments:{reference_id}:{newest_unanswered_created_on}"


def build_changes_key(reference_id: str, changes_request_date: str) -> str:
    """Idempotency key for the changes lane.

    Carries the newest ``changes_request`` date so it is deterministic across reviewers (the latest
    changes-request wins) and re-queues only when a newer changes-request arrives.
    """
    return f"bitbucket:changes:{reference_id}:{changes_request_date}"
