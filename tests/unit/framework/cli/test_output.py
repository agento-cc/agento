"""Tests for colored output helpers."""
from __future__ import annotations

from unittest.mock import patch

from agento.framework.cli._output import cyan, log_error, log_info, log_warn


class TestOutput:
    def test_log_info_no_color(self, capsys):
        with patch("agento.framework.cli._output._supports_color", return_value=False):
            log_info("test message")
        assert capsys.readouterr().out == "[agento] test message\n"

    def test_log_warn_no_color(self, capsys):
        with patch("agento.framework.cli._output._supports_color", return_value=False):
            log_warn("warning")
        assert capsys.readouterr().out == "[agento] WARN: warning\n"

    def test_log_error_no_color(self, capsys):
        with patch("agento.framework.cli._output._supports_color", return_value=False):
            log_error("error")
        assert capsys.readouterr().err == "[agento] ERROR: error\n"

    def test_cyan_no_color(self):
        with patch("agento.framework.cli._output._supports_color", return_value=False):
            assert cyan("text") == "text"

    def test_log_info_with_color(self, capsys):
        with patch("agento.framework.cli._output._supports_color", return_value=True):
            log_info("test")
        out = capsys.readouterr().out
        assert "[agento]" in out
        assert "test" in out

    def test_cyan_with_color(self):
        with patch("agento.framework.cli._output._supports_color", return_value=True):
            result = cyan("text")
        assert "text" in result
        assert "\033[" in result
