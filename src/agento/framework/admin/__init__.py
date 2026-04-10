from __future__ import annotations

import sys


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
        try:
            from textual import __version__ as _  # noqa: F401
        except ImportError:
            print("Error: textual is not installed. Run: pip install agento-core[admin]", file=sys.stderr)
            sys.exit(1)
        from .app import AdminApp
        app = AdminApp()
        app.run()
