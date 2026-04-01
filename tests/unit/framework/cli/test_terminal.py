"""Tests for arrow-key terminal selector."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agento.framework.cli.terminal import select


class TestSelectNonTTY:
    """Non-TTY fallback: numbered list with text input."""

    @patch("agento.framework.cli.terminal.sys")
    @patch("builtins.input", return_value="2")
    @patch("builtins.print")
    def test_returns_correct_index(self, mock_print, mock_input, mock_sys):
        mock_sys.stdin.isatty.return_value = False
        result = select("Pick one:", ["Alpha", "Beta", "Gamma"])
        assert result == 1  # 0-based index for "Beta"

    @patch("agento.framework.cli.terminal.sys")
    @patch("builtins.input", side_effect=["0", "abc", "2"])
    @patch("builtins.print")
    def test_invalid_then_valid_reprompts(self, mock_print, mock_input, mock_sys):
        mock_sys.stdin.isatty.return_value = False
        result = select("Pick:", ["A", "B"])
        assert result == 1  # "2" maps to index 1
        assert mock_input.call_count == 3

    @patch("agento.framework.cli.terminal.sys")
    @patch("builtins.input", return_value="1")
    @patch("builtins.print")
    def test_first_option(self, mock_print, mock_input, mock_sys):
        mock_sys.stdin.isatty.return_value = False
        result = select("Pick:", ["Only"])
        assert result == 0


class TestSelectTTY:
    """TTY mode: mock termios/tty/stdin.read for arrow-key simulation."""

    def _make_mocks(self):
        mock_sys = MagicMock()
        mock_sys.stdin.isatty.return_value = True
        mock_sys.stdin.fileno.return_value = 0
        mock_sys.stdout = MagicMock()
        mock_sys.stdout.isatty.return_value = True

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [0, 0, 0, 0, 0, 0, [0] * 32]
        mock_termios.TCSADRAIN = 1

        mock_tty = MagicMock()

        return mock_sys, mock_termios, mock_tty

    def test_arrow_down_then_enter(self):
        mock_sys, mock_termios, mock_tty = self._make_mocks()
        mock_sys.stdin.read = MagicMock(side_effect=["\x1b", "[", "B", "\r"])

        with patch("agento.framework.cli.terminal.sys", mock_sys), \
             patch("agento.framework.cli.terminal.termios", mock_termios), \
             patch("agento.framework.cli.terminal.tty", mock_tty), \
             patch("agento.framework.cli.terminal._supports_color", return_value=False):
            result = select("Pick:", ["First", "Second"])

        assert result == 1

    def test_enter_selects_first_by_default(self):
        mock_sys, mock_termios, mock_tty = self._make_mocks()
        mock_sys.stdin.read = MagicMock(return_value="\r")

        with patch("agento.framework.cli.terminal.sys", mock_sys), \
             patch("agento.framework.cli.terminal.termios", mock_termios), \
             patch("agento.framework.cli.terminal.tty", mock_tty), \
             patch("agento.framework.cli.terminal._supports_color", return_value=False):
            result = select("Pick:", ["A", "B"])

        assert result == 0

    def test_ctrl_c_raises_keyboard_interrupt(self):
        mock_sys, mock_termios, mock_tty = self._make_mocks()
        mock_sys.stdin.read = MagicMock(return_value="\x03")

        with patch("agento.framework.cli.terminal.sys", mock_sys), \
             patch("agento.framework.cli.terminal.termios", mock_termios), \
             patch("agento.framework.cli.terminal.tty", mock_tty), \
             patch("agento.framework.cli.terminal._supports_color", return_value=False), \
             pytest.raises(KeyboardInterrupt):
            select("Pick:", ["A", "B"])

    def test_terminal_restored_on_exception(self):
        mock_sys, mock_termios, mock_tty = self._make_mocks()
        old_settings = [0, 0, 0, 0, 0, 0, [0] * 32]
        mock_termios.tcgetattr.return_value = old_settings
        mock_sys.stdin.read = MagicMock(return_value="\x03")

        with patch("agento.framework.cli.terminal.sys", mock_sys), \
             patch("agento.framework.cli.terminal.termios", mock_termios), \
             patch("agento.framework.cli.terminal.tty", mock_tty), \
             patch("agento.framework.cli.terminal._supports_color", return_value=False), \
             pytest.raises(KeyboardInterrupt):
            select("Pick:", ["A"])

        # Verify terminal was restored in finally block
        mock_termios.tcsetattr.assert_called()
        restore_call = mock_termios.tcsetattr.call_args_list[-1]
        assert restore_call[0][0] == 0  # fd
        assert restore_call[0][2] == old_settings


class TestSelectValidation:
    def test_empty_options_raises(self):
        with pytest.raises(ValueError, match="options must not be empty"):
            select("Pick:", [])

    def test_wrap_around_up(self):
        """Arrow-up from first item wraps to last."""
        mock_sys = MagicMock()
        mock_sys.stdin.isatty.return_value = True
        mock_sys.stdin.fileno.return_value = 0
        mock_sys.stdout = MagicMock()
        mock_sys.stdout.isatty.return_value = True
        mock_sys.stdin.read = MagicMock(side_effect=["\x1b", "[", "A", "\r"])

        mock_termios = MagicMock()
        mock_termios.tcgetattr.return_value = [0, 0, 0, 0, 0, 0, [0] * 32]
        mock_termios.TCSADRAIN = 1

        with patch("agento.framework.cli.terminal.sys", mock_sys), \
             patch("agento.framework.cli.terminal.termios", mock_termios), \
             patch("agento.framework.cli.terminal.tty", MagicMock()), \
             patch("agento.framework.cli.terminal._supports_color", return_value=False):
            result = select("Pick:", ["First", "Second", "Third"])

        assert result == 2  # Wrapped to last
