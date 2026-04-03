"""Tests for CLI command shortcut registry."""
from __future__ import annotations

import argparse
import logging

import pytest

from agento.framework.commands import (
    clear,
    get_commands,
    get_shortcuts,
    register_command,
    resolve_shortcut,
)


class _StubCommand:
    def __init__(self, name: str, shortcut: str = ""):
        self._name = name
        self._shortcut = shortcut

    @property
    def name(self) -> str:
        return self._name

    @property
    def shortcut(self) -> str:
        return self._shortcut

    @property
    def help(self) -> str:
        return f"Help for {self._name}"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean():
    clear()
    yield
    clear()


class TestShortcutRegistration:
    def test_command_with_shortcut_registers_in_shortcuts(self):
        cmd = _StubCommand("setup:upgrade", "se:up")
        register_command(cmd)

        assert get_shortcuts() == {"se:up": "setup:upgrade"}
        assert "setup:upgrade" in get_commands()

    def test_command_with_empty_shortcut_not_in_shortcuts(self):
        cmd = _StubCommand("consumer", "")
        register_command(cmd)

        assert get_shortcuts() == {}
        assert "consumer" in get_commands()

    def test_shortcut_conflict_logs_warning_first_wins(self, caplog):
        cmd1 = _StubCommand("first:cmd", "fc")
        cmd2 = _StubCommand("second:cmd", "fc")

        register_command(cmd1)
        with caplog.at_level(logging.WARNING):
            register_command(cmd2)

        assert get_shortcuts() == {"fc": "first:cmd"}
        assert "already registered" in caplog.text

    def test_clear_resets_both_registries(self):
        register_command(_StubCommand("a:cmd", "ac"))
        assert get_commands()
        assert get_shortcuts()

        clear()

        assert get_commands() == {}
        assert get_shortcuts() == {}

    def test_get_shortcuts_returns_copy(self):
        register_command(_StubCommand("x:cmd", "xc"))
        shortcuts = get_shortcuts()
        shortcuts["injected"] = "bad"

        assert "injected" not in get_shortcuts()

    def test_get_commands_returns_copy(self):
        register_command(_StubCommand("y:cmd", "yc"))
        commands = get_commands()
        commands["injected"] = None

        assert "injected" not in get_commands()

    def test_multiple_commands_with_different_shortcuts(self):
        register_command(_StubCommand("config:set", "co:se"))
        register_command(_StubCommand("config:get", "co:ge"))
        register_command(_StubCommand("consumer", ""))

        assert get_shortcuts() == {"co:se": "config:set", "co:ge": "config:get"}
        assert len(get_commands()) == 3


class TestResolveShortcut:
    def test_resolves_known_shortcut(self):
        register_command(_StubCommand("config:set", "co:se"))

        assert resolve_shortcut("co:se") == "config:set"

    def test_returns_input_for_unknown_shortcut(self):
        assert resolve_shortcut("no:such") == "no:such"

    def test_returns_full_command_name_unchanged(self):
        register_command(_StubCommand("config:set", "co:se"))

        assert resolve_shortcut("config:set") == "config:set"

    def test_returns_empty_string_unchanged(self):
        assert resolve_shortcut("") == ""
