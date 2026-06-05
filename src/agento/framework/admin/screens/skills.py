from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import SelectionList, Static
from textual.widgets.selection_list import Selection

from ..data import EnablementItem, get_skill_states
from ._enablement import EnablementScreen, prompt_label


class SkillsScreen(EnablementScreen):
    """Opt-in skills as a single alphabetical checkbox list, per scope."""

    SIDEBAR_KEY = "skills"
    HINT = "Skills are opt-in (disabled by default). Check to enable for the selected scope."

    def fetch(self, conn) -> list[EnablementItem]:
        return get_skill_states(conn, self._scope, self._scope_id)

    def empty(self) -> list[EnablementItem]:
        return []

    async def render_data(self, skills: list[EnablementItem]) -> None:
        container = self.query_one(VerticalScroll)
        await container.remove_children()
        if not skills:
            await container.mount(
                Static("No skills registered. Run skill:sync first.", classes="enablement-empty")
            )
            return
        sel = SelectionList(
            *[Selection(prompt_label(s), s.path, s.enabled) for s in skills],
            classes="enablement-list",
        )
        sel.border_title = "skills"
        await container.mount(sel)
