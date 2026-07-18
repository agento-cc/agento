"""Stateless Outlook activation gate — pure logic, no DB/IO.

Decides whether the agent should respond to an inbound email from the current
message alone (its recipients + subject/body-preview + a distilled ``agent_authored``
boolean). No thread-state, no ACLs, no crypto — ``agent_authored`` is computed in the
toolbox (the message's From is one of the configured fleet mailboxes); here we only read
the resulting boolean.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SUBJECT_PREFIX = re.compile(r"^\s*(?:re|fwd|fw)\s*(?:\[\d+\])?\s*:\s*", re.IGNORECASE)


@dataclass
class Decision:
    can_respond: bool
    reason: str


def normalize_subject(subject: str | None) -> str:
    """Lowercase and strip leading Re:/Fwd:/Fw: reply-prefixes (repeated) + whitespace."""
    s = (subject or "").strip()
    while True:
        stripped = _SUBJECT_PREFIX.sub("", s, count=1).strip()
        if stripped == s:
            break
        s = stripped
    return s.lower()


def has_summon_token(text: str | None, token: str) -> bool:
    """Literal, case-insensitive, word-boundary-ish match of ``token`` in ``text``.

    Not fuzzy intent: the token must sit between non-alphanumeric boundaries so an
    embedded occurrence (e.g. ``@agento`` inside ``user@agento.com`` or ``@agentozord``)
    does not count as a summon.
    """
    tok = (token or "").strip().lower()
    if not tok:
        return False
    hay = (text or "").lower()
    start = 0
    while True:
        idx = hay.find(tok, start)
        if idx == -1:
            return False
        before = hay[idx - 1] if idx > 0 else ""
        after_idx = idx + len(tok)
        after = hay[after_idx] if after_idx < len(hay) else ""
        if not before.isalnum() and not after.isalnum():
            return True
        start = idx + 1


def _addr_list(items) -> list[str]:
    """Normalize a Graph recipient list ([{name,address}, ...] or [str, ...]) to lowercased addresses."""
    out: list[str] = []
    for it in items or []:
        addr = it.get("address") if isinstance(it, dict) else it
        if addr:
            out.append(str(addr).strip().lower())
    return out


def is_direct_addressed(match_set: set[str], to_addrs, cc_addrs, require_sole: bool) -> bool:
    """True if the mailbox (its UPN + aliases = ``match_set``) is addressed on to/cc.

    When ``require_sole`` is set the mailbox must be the ONLY recipient across to+cc.
    """
    recipients = _addr_list(to_addrs) + _addr_list(cc_addrs)
    if not recipients:
        return False
    if not any(r in match_set for r in recipients):
        return False
    if require_sole:
        return all(r in match_set for r in recipients)
    return True


def decide(
    *, agent_authored: bool, cfg, mailbox: str | None, aliases,
    to_addrs, cc_addrs, subject: str | None, body_preview: str | None,
) -> Decision:
    """Decide whether to respond to one inbound email. Pure function.

    An agent-authored message (``agent_authored`` — the sender is a fleet agent mailbox)
    hard-suppresses unless ``allow_bot_collaboration`` is opted in. Otherwise respond iff an
    active mode fires: ``direct`` (addressed to the mailbox)
    or ``mention`` (summon token in the normalized subject or the body preview).
    """
    if agent_authored and not cfg.allow_bot_collaboration:
        return Decision(can_respond=False, reason="agent_authored")

    modes = cfg.activation_modes_set
    match_set = {
        a for a in [(mailbox or "").strip().lower(), *[(x or "").strip().lower() for x in (aliases or [])]] if a
    }

    if "direct" in modes and is_direct_addressed(
        match_set, to_addrs, cc_addrs, cfg.direct_requires_sole_recipient
    ):
        return Decision(can_respond=True, reason="direct")

    if "mention" in modes and (
        has_summon_token(normalize_subject(subject), cfg.summon_token)
        or has_summon_token(body_preview, cfg.summon_token)
    ):
        return Decision(can_respond=True, reason="mention")

    return Decision(can_respond=False, reason="no_active_mode")
