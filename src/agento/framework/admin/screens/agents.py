from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class AgentsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static("Agents -- Coming soon", id="placeholder")
