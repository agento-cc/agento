"""Colored terminal output helpers."""
from __future__ import annotations

import sys

_RED = "\033[0;31m"
_GREEN = "\033[0;32m"
_YELLOW = "\033[1;33m"
_CYAN = "\033[0;36m"
_NC = "\033[0m"


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def log_info(msg: str) -> None:
    if _supports_color():
        print(f"{_GREEN}[agento]{_NC} {msg}")
    else:
        print(f"[agento] {msg}")


def log_warn(msg: str) -> None:
    if _supports_color():
        print(f"{_YELLOW}[agento]{_NC} {msg}")
    else:
        print(f"[agento] WARN: {msg}")


def log_error(msg: str) -> None:
    if _supports_color():
        print(f"{_RED}[agento]{_NC} {msg}", file=sys.stderr)
    else:
        print(f"[agento] ERROR: {msg}", file=sys.stderr)


def cyan(msg: str) -> str:
    if _supports_color():
        return f"{_CYAN}{msg}{_NC}"
    return msg
