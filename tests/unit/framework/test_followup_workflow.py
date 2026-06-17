from agento.framework.channels.base import PromptFragments
from agento.framework.workflows.base import Workflow
from agento.framework.workflows.followup import FollowupWorkflow


def test_followup_workflow_is_a_workflow():
    assert issubclass(FollowupWorkflow, Workflow)


def test_build_prompt_includes_instructions_context():
    class FakeChannel:
        name = "fake"

        def get_followup_fragments(self, reference_id, instructions):
            return PromptFragments(
                read_context=f"READ {reference_id}",
                respond="RESPOND",
                extra=f"KONTEKST\n{instructions}",
            )

    wf = FollowupWorkflow(runner=None, logger=None)
    prompt = wf.build_prompt(FakeChannel(), "REF-1", instructions="do the thing")
    assert "do the thing" in prompt
    assert "READ REF-1" in prompt
