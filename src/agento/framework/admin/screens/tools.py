from __future__ import annotations

from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, SelectionList, Static
from textual.widgets.selection_list import Selection

from ..data import EnablementItem, get_tool_states
from ._enablement import EnablementScreen, prompt_label

_TOGGLE_PREFIX = "toolset-all-"
_LIST_PREFIX = "toolset-list-"


class ToolsScreen(EnablementScreen):
    """Opt-in tools, grouped into sections per toolset (alphabetical within).

    Each toolset has a 'toggle all' button that enables the whole group if any
    member is off, or disables it when all are on.
    """

    SIDEBAR_KEY = "tools"
    # No square brackets — Textual's Static parses [..] as console markup.
    HINT = "Tools are opt-in. Toggle a tool, or use a toolset's toggle-all button."

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._groups: list[tuple[str, list[EnablementItem]]] = []

    def fetch(self, conn) -> list[tuple[str, list[EnablementItem]]]:
        return get_tool_states(conn, self._scope, self._scope_id)

    def empty(self) -> list[tuple[str, list[EnablementItem]]]:
        return []

    async def render_data(self, groups: list[tuple[str, list[EnablementItem]]]) -> None:
        self._groups = groups
        container = self.query_one(VerticalScroll)
        await container.remove_children()
        if not groups:
            await container.mount(Static("No tools registered.", classes="enablement-empty"))
            return
        for i, (toolset, items) in enumerate(groups):
            sel = SelectionList(
                *[Selection(prompt_label(it), it.path, it.enabled) for it in items],
                id=f"{_LIST_PREFIX}{i}",
                classes="enablement-list",
            )
            sel.border_title = f"toolset: {toolset}"
            await container.mount(
                Vertical(
                    Button(f"{toolset}  —  toggle all", id=f"{_TOGGLE_PREFIX}{i}", classes="toolset-header"),
                    sel,
                    classes="toolset-section",
                )
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if not bid.startswith(_TOGGLE_PREFIX):
            return
        idx = int(bid[len(_TOGGLE_PREFIX):])
        _toolset, items = self._groups[idx]
        sel = self.query_one(f"#{_LIST_PREFIX}{idx}", SelectionList)
        all_on = len(sel.selected) == len(items)
        # Update the UI immediately, persist in the background. select_all/
        # deselect_all post a single SelectedChanged (not per-item
        # SelectionToggled), so this does not double-fire the toggle handler.
        if all_on:
            sel.deselect_all()
            value = "0"
        else:
            sel.select_all()
            value = "1"
        self.write_paths([(it.path, value) for it in items])
