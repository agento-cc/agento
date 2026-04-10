from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from .screens.agents import AgentsScreen
from .screens.config import ConfigScreen
from .screens.dashboard import DashboardScreen
from .screens.jobs import JobsScreen
from .screens.tokens import TokensScreen

CSS_PATH = Path(__file__).parent / "styles" / "admin.tcss"


class AdminApp(App):
    TITLE = "Agento Admin"
    CSS_PATH = CSS_PATH

    BINDINGS = [  # noqa: RUF012
        Binding("f1", "switch_screen('dashboard')", "F1 Dashboard", show=True),
        Binding("f2", "switch_screen('jobs')", "F2 Jobs", show=True),
        Binding("f3", "switch_screen('tokens')", "F3 Tokens", show=True),
        Binding("f4", "switch_screen('agents')", "F4 Agents", show=True),
        Binding("f5", "switch_screen('config')", "F5 Config", show=True),
        Binding("r", "refresh", "r Refresh", show=True),
        Binding("q", "quit", "q Quit", show=True),
        Binding("ctrl+x", "quit", "^X Quit", show=True, priority=True),
    ]

    SCREENS = {  # noqa: RUF012
        "dashboard": DashboardScreen,
        "jobs": JobsScreen,
        "tokens": TokensScreen,
        "agents": AgentsScreen,
        "config": ConfigScreen,
    }

    conn = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        self._connect_db()
        self.push_screen("dashboard")

    def _connect_db(self) -> None:
        try:
            from ..database_config import DatabaseConfig
            from ..db import get_connection

            config = DatabaseConfig.from_env()
            self.conn = get_connection(config)
        except Exception:
            self.conn = None

    def action_refresh(self) -> None:
        screen = self.screen
        if hasattr(screen, "action_refresh"):
            screen.action_refresh()

    async def action_switch_screen(self, screen: str) -> None:
        self.switch_screen(screen)
