"""Minimal arrow-key terminal selector — stdlib only (sys, tty, termios)."""
from __future__ import annotations

import sys

try:
    import termios
    import tty
except ImportError:  # Windows — TTY mode unavailable
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

from ._output import _CYAN, _NC, _supports_color

_BOLD = "\033[1m"


def select(prompt: str, options: list[str]) -> int:
    """Arrow-key selector. Returns selected index (0-based).

    TTY mode: renders options with arrow-key navigation.
    Non-TTY fallback: numbered list with text input.
    """
    if not options:
        raise ValueError("options must not be empty")

    if termios is not None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        return _select_tty(prompt, options)
    return _select_fallback(prompt, options)


def _select_tty(prompt: str, options: list[str]) -> int:
    """Interactive arrow-key selector for TTY terminals."""
    assert termios is not None
    assert tty is not None
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    selected = 0

    def _render(*, move_up: bool = True) -> None:
        use_color = _supports_color()
        if move_up:
            sys.stdout.write(f"\033[{len(options)}A")
        for i, opt in enumerate(options):
            if move_up:
                sys.stdout.write("\033[2K\r")
            if i == selected:
                prefix = ">"
                if use_color:
                    sys.stdout.write(f"  {_BOLD}{_CYAN}{prefix} {opt}{_NC}\n")
                else:
                    sys.stdout.write(f"  {prefix} {opt}\n")
            else:
                sys.stdout.write(f"    {opt}\n")
        sys.stdout.flush()

    try:
        sys.stdout.write(f"\n  {prompt}\n")
        _render(move_up=False)

        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\r" or ch == "\n":
                break
            if ch == "\x03":  # Ctrl-C
                raise KeyboardInterrupt
            if ch == "\x1b":  # Escape sequence
                seq1 = sys.stdin.read(1)
                if seq1 == "[":
                    seq2 = sys.stdin.read(1)
                    if seq2 == "A":  # Up
                        selected = (selected - 1) % len(options)
                    elif seq2 == "B":  # Down
                        selected = (selected + 1) % len(options)

            # Restore temporarily to render
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            _render()
            tty.setraw(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return selected


def _select_fallback(prompt: str, options: list[str]) -> int:
    """Numbered-list fallback for non-TTY (CI/pipe)."""
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"    {i}) {opt}")

    while True:
        raw = input(f"  Select [1-{len(options)}]: ").strip()
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
        except ValueError:
            pass
        print(f"  Invalid choice. Enter a number between 1 and {len(options)}.")
