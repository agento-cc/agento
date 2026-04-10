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
        Binding("d", "switch_screen('dashboard')", "Dashboard"),
        Binding("j", "switch_screen('jobs')", "Jobs"),
        Binding("t", "switch_screen('tokens')", "Tokens"),
        Binding("a", "switch_screen('agents')", "Agents"),
        Binding("c", "switch_screen('config')", "Config"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
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

    def action_help(self) -> None:
        self.notify(
            "d=Dashboard  j=Jobs  t=Tokens  a=Agents  c=Config  r=Refresh  q=Quit",
            title="Key Bindings",
        )

    async def action_switch_screen(self, screen: str) -> None:
        self.switch_screen(screen)
