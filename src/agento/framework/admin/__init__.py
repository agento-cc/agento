from __future__ import annotations


class AdminCommand:
    @property
    def name(self) -> str:
        return "admin"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Launch the admin terminal interface"

    def configure(self, parser) -> None:
        pass

    def execute(self, args) -> None:
        from .app import AdminApp

        AdminApp().run()
