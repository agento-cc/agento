from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class TokensScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static("Tokens -- Coming soon", id="placeholder")
