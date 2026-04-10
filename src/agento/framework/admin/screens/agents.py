from __future__ import annotations

import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Static
from textual import work


class ConfirmScreen(ModalScreen[bool]):

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.message)
            with Horizontal():
                yield Button("Confirm", variant="primary", id="confirm")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class AgentDetailScreen(ModalScreen):

    BINDINGS = [  # noqa: RUF012
        Binding("escape", "pop_screen", "Esc Close", show=True),
    ]

    def __init__(self, agent: dict) -> None:
        self.agent = agent
        super().__init__()

    def compose(self) -> ComposeResult:
        a = self.agent
        with VerticalScroll(classes="panel"):
            yield Static(f"Agent View: {a['code']}", classes="panel-title")
            yield Static(
                f"Code: {a['code']}\n"
                f"Label: {a.get('label', '')}\n"
                f"Workspace: {a.get('workspace_code', '')}\n"
                f"Ingress bindings: {a.get('ingress_count', 0)}\n"
                f"Build status: {a.get('build_status', 'none')}"
            )
            yield Static("\nPress 'b' to trigger workspace build, 'c' to view config")

    def action_pop_screen(self) -> None:
        self.app.pop_screen()


class AgentsScreen(Screen):

    BINDINGS = [  # noqa: RUF012
        Binding("enter", "view_detail", "Enter Detail", show=True),
        Binding("b", "build", "b Build", show=True),
        Binding("c", "switch_screen('config')", "c Config", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="agents-list-panel", classes="panel"):
            yield Static("Agent Views", classes="panel-title")
            yield DataTable(id="agents-table")
        with Vertical(id="agent-detail-panel", classes="panel"):
            yield Static("Agent Detail", classes="panel-title")
            yield Static("Select an agent view above", id="agent-detail-content")

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

    def action_view_detail(self) -> None:
        agent = self._get_selected_agent()
        if agent:
            self.app.push_screen(AgentDetailScreen(agent))

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
                ["agento", "workspace:build", "--agent-view", code],
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
