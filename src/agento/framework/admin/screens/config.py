from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class ConfigScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static("Config -- Coming soon", id="placeholder")
