from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class JobsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static("Jobs -- Coming soon", id="placeholder")
