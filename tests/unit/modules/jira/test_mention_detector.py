"""Tests for mention_detector — uses real Jira v2 API comment format."""
from __future__ import annotations

from agento.modules.jira.src.mention_detector import find_unanswered_mention

# Real accountId format from Jira Cloud
AGENT_ID = "712020:1c7cf814-5a70-4333-96e5-ccc9f0b36bcc"
USER_MARCIN = "5ccae0c92ba2de10052c1d99"
USER_ANNA = "5a1234567890abcdef123456"


def _comment(
    id: str,
    author_id: str,
    body: str = "",
    *,
    display_name: str = "User",
    email: str | None = None,
) -> dict:
    """Build a comment dict matching the real Jira v2 API response shape."""
    author: dict = {
        "accountId": author_id,
        "displayName": display_name,
        "avatarUrls": {},
        "active": True,
        "timeZone": "Europe/Warsaw",
        "accountType": "atlassian",
    }
    if email:
        author["emailAddress"] = email
    return {
        "self": f"https://company.atlassian.net/rest/api/2/issue/103465/comment/{id}",
        "id": id,
        "author": author,
        "updateAuthor": author,
        "body": body,
        "created": "2026-03-04T13:35:01.839+0100",
        "updated": "2026-03-04T13:35:01.839+0100",
        "jsdPublic": True,
    }


class TestFindUnansweredMention:
    """Core detection logic."""

    def test_no_comments(self):
        assert find_unanswered_mention([], AGENT_ID) is None

    def test_no_mention_in_comments(self):
        comments = [
            _comment("100", USER_MARCIN, "Just a regular comment", display_name="Marcin Klauza"),
        ]
        assert find_unanswered_mention(comments, AGENT_ID) is None

    def test_unanswered_mention_lowercase_accountid(self):
        """Real Jira v2 body uses [~accountid:...] (lowercase)."""
        comments = [
            _comment(
                "150318", USER_MARCIN,
                f"[~accountid:{AGENT_ID}] \nPodaj mi dane sprzedaży",
                display_name="Marcin Klauza",
            ),
        ]
        result = find_unanswered_mention(comments, AGENT_ID)
        assert result is not None
        assert result["id"] == "150318"

    def test_unanswered_mention_uppercase_accountId(self):
        """Also match [~accountId:...] (camelCase) for safety."""
        comments = [
            _comment("200", USER_MARCIN, f"[~accountId:{AGENT_ID}] help"),
        ]
        result = find_unanswered_mention(comments, AGENT_ID)
        assert result is not None
        assert result["id"] == "200"

    def test_answered_mention(self):
        """Agent replied after the mention — should return None."""
        comments = [
            _comment(
                "150318", USER_MARCIN,
                f"[~accountid:{AGENT_ID}] podaj raport",
                display_name="Marcin Klauza",
            ),
            _comment(
                "150308", AGENT_ID,
                "h3. Raport sprzedaży\n\nDane pobrane z K3...",
                display_name="Mieszko",
                email="agenty@example.com",
            ),
        ]
        assert find_unanswered_mention(comments, AGENT_ID) is None

    def test_agent_comment_first_then_mention(self):
        """Agent's old comment, then new mention — unanswered."""
        comments = [
            _comment(
                "150308", AGENT_ID,
                "h3. Raport sprzedaży...",
                display_name="Mieszko",
                email="agenty@example.com",
            ),
            _comment(
                "150318", USER_MARCIN,
                f"[~accountid:{AGENT_ID}] \nPodaj dane zagregowane po kategorii",
                display_name="Marcin Klauza",
            ),
        ]
        result = find_unanswered_mention(comments, AGENT_ID)
        assert result is not None
        assert result["id"] == "150318"


class TestMultipleMentions:
    """Scenarios with multiple mentions from different users."""

    def test_latest_mention_unanswered(self):
        comments = [
            _comment("1", USER_MARCIN, f"[~accountid:{AGENT_ID}] first request"),
            _comment("2", AGENT_ID, "Done with first", email="agenty@example.com"),
            _comment("3", USER_ANNA, f"[~accountid:{AGENT_ID}] second request"),
        ]
        result = find_unanswered_mention(comments, AGENT_ID)
        assert result is not None
        assert result["id"] == "3"

    def test_all_mentions_answered(self):
        comments = [
            _comment("1", USER_MARCIN, f"[~accountid:{AGENT_ID}] first"),
            _comment("2", AGENT_ID, "Reply to first", email="agenty@example.com"),
            _comment("3", USER_ANNA, f"[~accountid:{AGENT_ID}] second"),
            _comment("4", AGENT_ID, "Reply to second", email="agenty@example.com"),
        ]
        assert find_unanswered_mention(comments, AGENT_ID) is None

    def test_non_mention_comment_after_mention(self):
        """Other users commenting after the mention doesn't count as agent reply."""
        comments = [
            _comment("1", USER_MARCIN, f"[~accountid:{AGENT_ID}] please help"),
            _comment("2", USER_ANNA, "I agree, this needs attention"),
            _comment("3", USER_MARCIN, "Bump"),
        ]
        result = find_unanswered_mention(comments, AGENT_ID)
        assert result is not None
        assert result["id"] == "1"


class TestEdgeCases:
    """Edge cases and data quality issues."""

    def test_agent_own_mention_ignored(self):
        """Agent quoting/mentioning itself is not a mention to respond to."""
        comments = [
            _comment("1", AGENT_ID, f"I am [~accountid:{AGENT_ID}]", email="agenty@example.com"),
        ]
        assert find_unanswered_mention(comments, AGENT_ID) is None

    def test_empty_body(self):
        comments = [_comment("1", USER_MARCIN, "")]
        assert find_unanswered_mention(comments, AGENT_ID) is None

    def test_body_none(self):
        comment = {
            "id": "1",
            "author": {"accountId": USER_MARCIN},
            "body": None,
            "created": "2026-03-01T10:00:00.000+0100",
        }
        assert find_unanswered_mention([comment], AGENT_ID) is None

    def test_author_missing(self):
        """Comment with no author dict — should not crash."""
        comment = {"id": "1", "author": None, "body": f"[~accountid:{AGENT_ID}]", "created": ""}
        result = find_unanswered_mention([comment], AGENT_ID)
        assert result is not None
        assert result["id"] == "1"

    def test_mention_embedded_in_long_body(self):
        """Mention pattern buried inside Jira wiki markup body."""
        body = (
            "h3. Prośba o raport\n\n"
            f"[~accountid:{AGENT_ID}] \n"
            "Podaj mi dane dot. ilości sprzedanych szt. online w K3\n"
            "produktów zagregowane po kategorii.\n\n"
            "Oczekiwany rezultat:\n"
            "# Tabela z danymi\n"
            "# SQL do przyszłych raportów"
        )
        comments = [_comment("150318", USER_MARCIN, body, display_name="Marcin Klauza")]
        result = find_unanswered_mention(comments, AGENT_ID)
        assert result is not None

    def test_mention_of_different_user_ignored(self):
        """Mention of a different accountId should not trigger."""
        comments = [
            _comment("1", USER_MARCIN, f"[~accountid:{USER_ANNA}] check this"),
        ]
        assert find_unanswered_mention(comments, AGENT_ID) is None

    def test_partial_accountid_no_match(self):
        """Partial match should not trigger (e.g. truncated ID)."""
        partial_id = AGENT_ID[:20]
        comments = [
            _comment("1", USER_MARCIN, f"[~accountid:{partial_id}]"),
        ]
        assert find_unanswered_mention(comments, AGENT_ID) is None
