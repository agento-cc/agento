from __future__ import annotations

import subprocess

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from ..widgets.confirm import ConfirmScreen
from ..widgets.sidebar import Sidebar


class AgentsScreen(Screen):

    BINDINGS = [  # noqa: RUF012
        Binding("b", "build", "b Build", show=True),
        Binding("c", "switch_screen('config')", "c Config", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Sidebar(active="agents")
        with VerticalScroll(classes="screen-content"):
            with Vertical(id="agents-list-panel", classes="panel"):
                yield Static("Agent Views", classes="panel-title")
                yield DataTable(id="agents-table")
            with Vertical(id="agent-detail-panel", classes="panel"):
                yield Static("Agent Detail", classes="panel-title")
                yield Static("Select an agent view above", id="agent-detail-content")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.add_columns("Code", "Workspace", "Ingress", "Build Status")
        table.cursor_type = "row"
        self._agents: list[dict] = []
        self._load_data()

    def action_refresh(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        from ..data import get_agents_summary

        agents = get_agents_summary(self.app.conn)
        self.app.call_from_thread(self._update_ui, agents)

    def _update_ui(self, agents: list[dict]) -> None:
        self._agents = agents
        table = self.query_one("#agents-table", DataTable)
        table.clear()
        if agents:
            for agent in agents:
                table.add_row(
                    agent["code"],
                    agent.get("workspace_code", ""),
                    str(agent.get("ingress_count", 0)),
                    agent.get("build_status", "none"),
                )
        else:
            table.add_row("--", "--", "--", "No agent views found")

    def _get_selected_agent(self) -> dict | None:
        if not self._agents:
            return None
        table = self.query_one("#agents-table", DataTable)
        if table.cursor_row is not None and 0 <= table.cursor_row < len(self._agents):
            return self._agents[table.cursor_row]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_build()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        agent = self._get_selected_agent()
        if agent is None:
            return
        detail = (
            f"Code: {agent['code']}\n"
            f"Label: {agent.get('label', '')}\n"
            f"Workspace: {agent.get('workspace_code', '')}\n"
            f"Ingress bindings: {agent.get('ingress_count', 0)}\n"
            f"Build status: {agent.get('build_status', 'none')}"
        )
        self.query_one("#agent-detail-content", Static).update(detail)

    def action_build(self) -> None:
        agent = self._get_selected_agent()
        if agent is None:
            self.notify("No agent view selected", severity="warning")
            return
        code = agent["code"]
        self.app.push_screen(
            ConfirmScreen(f"Trigger workspace build for '{code}'?"),
            callback=lambda confirmed: self._on_build_confirmed(confirmed, code),
        )

    def _on_build_confirmed(self, confirmed: bool, code: str) -> None:
        if confirmed:
            self._run_build(code)

    @work(thread=True)
    def _run_build(self, code: str) -> None:
        try:
            result = subprocess.run(
                ["/opt/cron-agent/run.sh", "workspace:build", "--agent-view", code],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                self.app.call_from_thread(
                    self.notify, f"Build completed for '{code}'"
                )
            else:
                msg = result.stderr.strip() or f"Build failed (exit {result.returncode})"
                self.app.call_from_thread(
                    self.notify, msg, severity="error"
                )
        except subprocess.TimeoutExpired:
            self.app.call_from_thread(
                self.notify, f"Build timed out for '{code}'", severity="error"
            )
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, f"Build error: {exc}", severity="error"
            )
        self._load_data()
