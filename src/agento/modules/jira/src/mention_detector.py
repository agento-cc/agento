from __future__ import annotations


def find_unanswered_mention(
    comments: list[dict],
    agent_account_id: str,
) -> dict | None:
    """Return the latest comment that mentions the agent without a subsequent agent reply.

    Walks comments newest-first. A "mention" is a comment authored by someone
    else that contains the agent's accountId in the body via Jira @mention
    picker format: ``[~accountid:{agent_account_id}]`` (lowercase 'accountid'
    is what Jira v2 API returns in comment bodies).

    Returns the unanswered mention comment dict, or None if all mentions
    have been answered (or there are no mentions).
    """
    # Jira v2 API stores mentions as [~accountid:...] (lowercase 'accountid')
    # Match both cases to be safe
    patterns = (
        f"[~accountid:{agent_account_id}]",
        f"[~accountId:{agent_account_id}]",
    )
    agent_replied = False

    for comment in reversed(comments):
        author_id = (comment.get("author") or {}).get("accountId", "")

        if author_id == agent_account_id:
            agent_replied = True
            continue

        body = comment.get("body") or ""
        if any(p in body for p in patterns):
            if not agent_replied:
                return comment
            # Agent already replied after this mention
            return None

    return None
