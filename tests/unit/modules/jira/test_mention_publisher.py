"""Tests for JiraChannel.publish_mentions() orchestration.

Uses realistic Jira v2 API comment format based on actual API responses.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agento.framework.job_models import AgentType
from agento.modules.jira.src.channel import JiraChannel
from agento.modules.jira.src.config import JiraConfig
from agento.modules.jira.src.models import JiraIssue, TaskAction, TaskPriority, TaskSource

# Real accountId format from Jira Cloud
AGENT_ACCOUNT_ID = "712020:1c7cf814-5a70-4333-96e5-ccc9f0b36bcc"
USER_MARCIN = "5ccae0c92ba2de10052c1d99"
USER_ANNA = "5a1234567890abcdef123456"


def _make_config(**overrides) -> JiraConfig:
    defaults = dict(
        toolbox_url="http://toolbox:3001",
        user="mieszko@example.com",
        jira_projects=["AI"],
        jira_assignee="agenty@example.com",
        jira_assignee_account_id=AGENT_ACCOUNT_ID,
    )
    defaults.update(overrides)
    return JiraConfig(**defaults)


def _make_task(issue_key: str, *, status: str = "In Progress", summary: str = "Test task") -> TaskAction:
    return TaskAction(
        source=TaskSource.MENTION_UNANSWERED,
        priority=TaskPriority.HIGH,
        issue=JiraIssue(key=issue_key, summary=summary, status=status),
        reason="You were mentioned in a comment",
    )


def _jira_comment(
    id: str,
    author_id: str,
    body: str,
    *,
    display_name: str = "User",
    email: str | None = None,
) -> dict:
    """Build a comment dict matching real Jira v2 API response shape."""
    author: dict = {
        "self": f"https://example.atlassian.net/rest/api/2/user?accountId={author_id}",
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
        "self": f"https://example.atlassian.net/rest/api/2/issue/103465/comment/{id}",
        "id": id,
        "author": author,
        "updateAuthor": author,
        "body": body,
        "created": "2026-03-04T13:35:01.839+0100",
        "updated": "2026-03-04T13:35:01.839+0100",
        "jsdPublic": True,
    }


class TestPublishMentionsBasic:
    """Core publish_mentions orchestration."""

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_publishes_unanswered_mention(self, MockBuilder, MockToolbox, mock_publish):
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = [_make_task("AI-8")]
        MockBuilder.return_value = builder

        toolbox = MagicMock()
        toolbox.jira_get_comments.return_value = [
            _jira_comment(
                "150318", USER_MARCIN,
                f"[~accountid:{AGENT_ACCOUNT_ID}] \nPodaj mi dane sprzedaży",
                display_name="Marcin Klauza",
            ),
        ]
        MockToolbox.return_value = toolbox

        mock_publish.return_value = True

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 1
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][1] == AgentType.TODO
        assert call_args[0][2] == "jira"
        assert call_args[0][3] == "jira:mention:AI-8:150318"
        assert call_args[1]["reference_id"] == "AI-8"

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_skips_answered_mention(self, MockBuilder, MockToolbox, mock_publish):
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = [_make_task("AI-8")]
        MockBuilder.return_value = builder

        toolbox = MagicMock()
        toolbox.jira_get_comments.return_value = [
            _jira_comment(
                "150318", USER_MARCIN,
                f"[~accountid:{AGENT_ACCOUNT_ID}] podaj raport",
                display_name="Marcin Klauza",
            ),
            _jira_comment(
                "150308", AGENT_ACCOUNT_ID,
                "h3. Raport sprzedaży...",
                display_name="Mieszko",
                email="agenty@example.com",
            ),
        ]
        MockToolbox.return_value = toolbox

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 0
        mock_publish.assert_not_called()

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_no_candidates_from_jql(self, MockBuilder, MockToolbox, mock_publish):
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = []
        MockBuilder.return_value = builder

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 0
        mock_publish.assert_not_called()


class TestPublishMentionsConfig:
    """Configuration edge cases."""

    def test_missing_account_id_returns_zero(self):
        config = _make_config(jira_assignee_account_id="")
        logger = MagicMock()

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 0
        logger.warning.assert_called_once()

    def test_missing_assignee_and_user_returns_zero(self):
        config = _make_config(jira_assignee="", user="")
        logger = MagicMock()

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 0

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_uses_jira_assignee_for_jql(self, MockBuilder, MockToolbox, mock_publish):
        """TaskListBuilder should be created with jira_assignee email."""
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = []
        MockBuilder.return_value = builder

        channel = JiraChannel()
        channel.publish_mentions(config, logger)

        # Second positional arg to TaskListBuilder is config, third is ai_user
        MockBuilder.assert_called_once()
        ai_user_arg = MockBuilder.call_args[0][2]
        assert ai_user_arg == "agenty@example.com"


class TestPublishMentionsMultipleCandidates:
    """Multiple issues returned by JQL."""

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_multiple_issues_some_unanswered(self, MockBuilder, MockToolbox, mock_publish):
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = [
            _make_task("AI-8", status="In Progress"),
            _make_task("AI-10", status="To Do"),
            _make_task("AI-11", status="Review"),
        ]
        MockBuilder.return_value = builder

        toolbox = MagicMock()
        toolbox.jira_get_comments.side_effect = [
            # AI-8: answered
            [
                _jira_comment("100", USER_MARCIN, f"[~accountid:{AGENT_ACCOUNT_ID}] check"),
                _jira_comment("101", AGENT_ACCOUNT_ID, "Done", email="agenty@example.com"),
            ],
            # AI-10: unanswered
            [
                _jira_comment("200", USER_ANNA, f"[~accountid:{AGENT_ACCOUNT_ID}] help"),
            ],
            # AI-11: no mention in comments (JQL false positive)
            [
                _jira_comment("300", USER_MARCIN, "This is just a comment"),
            ],
        ]
        MockToolbox.return_value = toolbox

        mock_publish.return_value = True

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 1
        assert mock_publish.call_args[0][3] == "jira:mention:AI-10:200"

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_error_on_one_candidate_continues(self, MockBuilder, MockToolbox, mock_publish):
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = [
            _make_task("AI-10"),
            _make_task("AI-11"),
        ]
        MockBuilder.return_value = builder

        toolbox = MagicMock()
        toolbox.jira_get_comments.side_effect = [
            Exception("Jira API timeout"),
            [_jira_comment("200", USER_MARCIN, f"[~accountid:{AGENT_ACCOUNT_ID}] help")],
        ]
        MockToolbox.return_value = toolbox

        mock_publish.return_value = True

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 1
        assert mock_publish.call_args[0][3] == "jira:mention:AI-11:200"
        logger.exception.assert_called_once()


class TestPublishMentionsIdempotency:
    """Deduplication via idempotency keys."""

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_duplicate_not_counted(self, MockBuilder, MockToolbox, mock_publish):
        """When publish returns False (duplicate key), count should be 0."""
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = [_make_task("AI-8")]
        MockBuilder.return_value = builder

        toolbox = MagicMock()
        toolbox.jira_get_comments.return_value = [
            _jira_comment("150318", USER_MARCIN, f"[~accountid:{AGENT_ACCOUNT_ID}] help"),
        ]
        MockToolbox.return_value = toolbox

        mock_publish.return_value = False  # duplicate

        channel = JiraChannel()
        count = channel.publish_mentions(config, logger)

        assert count == 0
        mock_publish.assert_called_once()

    @patch("agento.modules.jira.src.channel.publish")
    @patch("agento.modules.jira.src.channel.ToolboxClient")
    @patch("agento.modules.jira.src.channel.TaskListBuilder")
    def test_idempotency_key_format(self, MockBuilder, MockToolbox, mock_publish):
        """Key is jira:mention:{issue_key}:{comment_id} — comment_id-based, not time-based."""
        config = _make_config()
        logger = MagicMock()

        builder = MagicMock()
        builder.get_unanswered_mentions.return_value = [_make_task("AI-42")]
        MockBuilder.return_value = builder

        toolbox = MagicMock()
        toolbox.jira_get_comments.return_value = [
            _jira_comment("99999", USER_ANNA, f"[~accountid:{AGENT_ACCOUNT_ID}] urgent"),
        ]
        MockToolbox.return_value = toolbox

        mock_publish.return_value = True

        channel = JiraChannel()
        channel.publish_mentions(config, logger)

        idem_key = mock_publish.call_args[0][3]
        assert idem_key == "jira:mention:AI-42:99999"
        # Verify no time component in key
        assert "2026" not in idem_key
