from agento.framework.channels.base import PromptFragments
from agento.framework.workflows.base import Workflow
from agento.framework.workflows.todo import TodoWorkflow


def test_todo_workflow_is_a_workflow():
    assert issubclass(TodoWorkflow, Workflow)


def test_build_prompt_uses_channel_fragments():
    class FakeChannel:
        name = "fake"

        def get_prompt_fragments(self, reference_id):
            return PromptFragments(
                read_context=f"READ {reference_id}", respond="RESPOND"
            )

    wf = TodoWorkflow(runner=None, logger=None)
    prompt = wf.build_prompt(FakeChannel(), "REF-1")
    assert "READ REF-1" in prompt
    assert "RESPOND" in prompt
    assert "(fake)" in prompt
