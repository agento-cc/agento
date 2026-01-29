"""Safety net: assert new workflow+channel prompts contain same key instructions
as old hardcoded templates."""
from __future__ import annotations

from unittest.mock import MagicMock

from agento.modules.jira.src.channel import JiraChannel
from agento.modules.jira.src.workflows.cron import CronWorkflow
from agento.modules.jira.src.workflows.followup import FollowupWorkflow
from agento.modules.jira.src.workflows.todo import TodoWorkflow

JIRA = JiraChannel()



class TestCronPromptEquivalence:
    def setup_method(self):
        runner = MagicMock()
        logger = MagicMock()
        self.workflow = CronWorkflow(runner, logger)
        self.new = self.workflow.build_prompt(JIRA, "AI-123")

    def test_contains_jira_get_issue(self):
        assert "jira_get_issue" in self.new

    def test_contains_jira_add_comment(self):
        assert "jira_add_comment" in self.new

    def test_contains_issue_key(self):
        assert "AI-123" in self.new

    def test_no_status_change_warning(self):
        assert "Nie zmieniaj statusu" in self.new

    def test_cykliczne(self):
        assert "cykliczne" in self.new.lower()

    def test_previous_results_hint(self):
        assert "poprzednich uruchomień" in self.new


class TestTodoPromptEquivalence:
    def setup_method(self):
        runner = MagicMock()
        logger = MagicMock()
        self.workflow = TodoWorkflow(runner, logger)
        self.new = self.workflow.build_prompt(JIRA, "AI-456")

    def test_contains_jira_get_issue(self):
        assert "jira_get_issue" in self.new

    def test_contains_jira_transition_issue(self):
        assert "jira_transition_issue" in self.new

    def test_contains_in_progress(self):
        assert "In Progress" in self.new

    def test_contains_review(self):
        assert "Review" in self.new

    def test_contains_jira_add_comment(self):
        assert "jira_add_comment" in self.new

    def test_contains_jira_assign_issue(self):
        assert "jira_assign_issue" in self.new

    def test_contains_reporter(self):
        assert "reporter" in self.new

    def test_contains_issue_key(self):
        assert "AI-456" in self.new

    def test_has_six_steps(self):
        assert "KROK 6" in self.new

    def test_evaluate_step(self):
        assert "ZAKOŃCZ" in self.new

    def test_plan_and_execute(self):
        assert "Zaplanuj" in self.new


class TestFollowupPromptEquivalence:
    def setup_method(self):
        runner = MagicMock()
        logger = MagicMock()
        self.workflow = FollowupWorkflow(runner, logger)
        self.new = self.workflow.build_prompt(
            JIRA, "AI-789", instructions="Sprawdź reindeks"
        )

    def test_contains_jira_get_issue(self):
        assert "jira_get_issue" in self.new

    def test_contains_jira_add_comment(self):
        assert "jira_add_comment" in self.new

    def test_contains_schedule_followup(self):
        assert "schedule_followup" in self.new

    def test_contains_instructions(self):
        assert "Sprawdź reindeks" in self.new

    def test_contains_kontekst(self):
        assert "KONTEKST" in self.new

    def test_contains_review(self):
        assert "Review" in self.new

    def test_contains_reporter(self):
        assert "reporter" in self.new

    def test_is_followup(self):
        assert "follow-up" in self.new.lower()
