from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Static
from textual.worker import work


class ConfirmScreen(ModalScreen[bool]):

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #confirm-dialog Static {
        margin-bottom: 1;
    }
    #confirm-dialog Horizontal {
        height: auto;
        align: center middle;
    }
    #confirm-dialog Button {
        margin: 0 1;
    }
    """

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


class TokenUsageScreen(ModalScreen):

    BINDINGS = [  # noqa: RUF012
        Binding("escape", "pop_screen", "Close"),
    ]

    DEFAULT_CSS = """
    TokenUsageScreen {
        align: center middle;
    }
    #token-detail {
        width: 70;
        height: auto;
        max-height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #token-detail-title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def __init__(self, token: dict) -> None:
        self.token = token
        super().__init__()

    def compose(self) -> ComposeResult:
        t = self.token
        with VerticalScroll(id="token-detail"):
            yield Static(
                f"Token #{t['id']} -- {t['label']}",
                id="token-detail-title",
            )
            primary = "yes" if t["is_primary"] else "no"
            enabled = "yes" if t["enabled"] else "no"
            limit = str(t["token_limit"]) if t["token_limit"] > 0 else "unlimited"
            pct = f"{t['pct_free']:.1f}%" if t["token_limit"] > 0 else "-"
            yield Static(
                f"Type:        {t['agent_type']}\n"
                f"Model:       {t['model']}\n"
                f"Primary:     {primary}\n"
                f"Enabled:     {enabled}\n"
                f"Token limit: {limit}\n"
                f"Used (24h):  {t['tokens_used']:,}\n"
                f"Calls (24h): {t['call_count']}\n"
                f"Free:        {pct}"
            )

    def action_pop_screen(self) -> None:
        self.app.pop_screen()


class TokensScreen(Screen):

    BINDINGS = [  # noqa: RUF012
        Binding("enter", "view_token", "View", show=False),
        Binding("s", "set_primary", "Set Primary"),
        Binding("x", "deregister", "Deregister"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tokens: list[dict] = []

    def compose(self) -> ComposeResult:
        with Container(id="tokens-list-panel", classes="panel"):
            yield Static("Tokens", classes="panel-title")
            yield DataTable(id="tokens-table")
        with Container(id="token-detail-panel", classes="panel"):
            yield Static("Token Detail", classes="panel-title")
            yield Static("Select a token to view details", id="token-detail-content")

    def on_mount(self) -> None:
        table = self.query_one("#tokens-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "ID", "Type", "Label", "Model", "Primary", "Limit",
            "Used (24h)", "Free%", "Enabled",
        )
        self._load_data()

    def action_refresh(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        from ..data import get_tokens_with_usage

        tokens = get_tokens_with_usage(self.app.conn)
        self.app.call_from_thread(self._update_ui, tokens)

    def _update_ui(self, tokens: list[dict]) -> None:
        self._tokens = tokens
        table = self.query_one("#tokens-table", DataTable)
        table.clear()
        if tokens:
            for t in tokens:
                primary = "*" if t["is_primary"] else ""
                limit = str(t["token_limit"]) if t["token_limit"] > 0 else "unlimited"
                pct = f"{t['pct_free']:.1f}" if t["token_limit"] > 0 else "-"
                enabled = "yes" if t["enabled"] else "no"
                table.add_row(
                    str(t["id"]),
                    t["agent_type"],
                    t["label"],
                    t["model"],
                    primary,
                    limit,
                    str(t["tokens_used"]),
                    pct,
                    enabled,
                    key=str(t["id"]),
                )
        else:
            table.add_row("--", "--", "No tokens registered", "--", "--", "--", "--", "--", "--")
        self._update_detail_panel()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        token = self._get_selected_token()
        detail = self.query_one("#token-detail-content", Static)
        if token is None:
            detail.update("Select a token to view details")
            return
        primary = "yes" if token["is_primary"] else "no"
        enabled = "yes" if token["enabled"] else "no"
        limit = str(token["token_limit"]) if token["token_limit"] > 0 else "unlimited"
        pct = f"{token['pct_free']:.1f}%" if token["token_limit"] > 0 else "-"
        detail.update(
            f"ID:          {token['id']}\n"
            f"Type:        {token['agent_type']}\n"
            f"Label:       {token['label']}\n"
            f"Model:       {token['model']}\n"
            f"Primary:     {primary}\n"
            f"Enabled:     {enabled}\n"
            f"Token limit: {limit}\n"
            f"Used (24h):  {token['tokens_used']:,}\n"
            f"Calls (24h): {token['call_count']}\n"
            f"Free:        {pct}"
        )

    def _get_selected_token(self) -> dict | None:
        if not self._tokens:
            return None
        table = self.query_one("#tokens-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._tokens):
            return None
        row_key = table.get_row_at(table.cursor_row)
        token_id = row_key[0]
        for t in self._tokens:
            if str(t["id"]) == token_id:
                return t
        return None

    def action_view_token(self) -> None:
        token = self._get_selected_token()
        if token:
            self.app.push_screen(TokenUsageScreen(token))

    def action_set_primary(self) -> None:
        token = self._get_selected_token()
        if not token:
            return
        self.app.push_screen(
            ConfirmScreen(f"Set token #{token['id']} ({token['label']}) as primary for {token['agent_type']}?"),
            callback=lambda confirmed: self._do_set_primary(token) if confirmed else None,
        )

    @work(thread=True)
    def _do_set_primary(self, token: dict) -> None:
        from ..data import do_set_primary_token

        do_set_primary_token(self.app.conn, token["agent_type"], token["id"])
        self.app.call_from_thread(self.notify, f"Token #{token['id']} set as primary")
        self.app.call_from_thread(self._load_data)

    def action_deregister(self) -> None:
        token = self._get_selected_token()
        if not token:
            return
        self.app.push_screen(
            ConfirmScreen(f"Deregister token #{token['id']} ({token['label']})? This cannot be undone."),
            callback=lambda confirmed: self._do_deregister(token) if confirmed else None,
        )

    @work(thread=True)
    def _do_deregister(self, token: dict) -> None:
        from ..data import do_deregister_token

        do_deregister_token(self.app.conn, token["id"])
        self.app.call_from_thread(self.notify, f"Token #{token['id']} deregistered")
        self.app.call_from_thread(self._load_data)
