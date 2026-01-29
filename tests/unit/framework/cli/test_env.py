"""Tests for .env file parser."""
from __future__ import annotations

from pathlib import Path

from agento.framework.cli._env import parse_env_file


class TestParseEnvFile:
    def test_simple_key_value(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        assert parse_env_file(env_file) == {"KEY": "value"}

    def test_skips_comments(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY=value\n")
        assert parse_env_file(env_file) == {"KEY": "value"}

    def test_skips_empty_lines(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("\nKEY=value\n\n")
        assert parse_env_file(env_file) == {"KEY": "value"}

    def test_strips_double_quotes(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text('KEY="quoted value"\n')
        assert parse_env_file(env_file) == {"KEY": "quoted value"}

    def test_strips_single_quotes(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY='quoted value'\n")
        assert parse_env_file(env_file) == {"KEY": "quoted value"}

    def test_empty_value(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=\n")
        assert parse_env_file(env_file) == {"KEY": ""}

    def test_value_with_equals(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=a=b=c\n")
        assert parse_env_file(env_file) == {"KEY": "a=b=c"}

    def test_multiple_entries(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\nB=2\nC=3\n")
        assert parse_env_file(env_file) == {"A": "1", "B": "2", "C": "3"}

    def test_nonexistent_file(self, tmp_path: Path):
        assert parse_env_file(tmp_path / "missing") == {}

    def test_skips_lines_without_equals(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("INVALID\nKEY=value\n")
        assert parse_env_file(env_file) == {"KEY": "value"}
