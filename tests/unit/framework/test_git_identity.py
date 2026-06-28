"""Tests for git commit author identity helpers (gitconfig block + env override)."""
from __future__ import annotations

from agento.framework.git_identity import (
    GIT_AUTHOR_EMAIL_PATH,
    GIT_AUTHOR_NAME_PATH,
    clean_identity_value,
    git_identity_env,
    gitconfig_user_block,
)


class TestPaths:
    def test_paths_are_agent_view_scoped(self):
        assert GIT_AUTHOR_NAME_PATH == "agent_view/identity/git_author_name"
        assert GIT_AUTHOR_EMAIL_PATH == "agent_view/identity/git_author_email"


class TestCleanIdentityValue:
    def test_strips_control_chars_and_trims(self):
        assert clean_identity_value("  Mieszko\n\t ") == "Mieszko"
        assert clean_identity_value("a\x00b\rc\nd") == "abcd"

    def test_empty_when_only_control_chars(self):
        assert clean_identity_value("\n\r\x00\x7f") == ""


class TestGitconfigUserBlock:
    def test_both(self):
        assert gitconfig_user_block("Mieszko", "m@example.com") == (
            '[user]\n\tname = "Mieszko"\n\temail = "m@example.com"\n'
        )

    def test_email_only(self):
        assert gitconfig_user_block("", "m@example.com") == '[user]\n\temail = "m@example.com"\n'

    def test_name_only(self):
        assert gitconfig_user_block("Mieszko", "") == '[user]\n\tname = "Mieszko"\n'

    def test_none_when_empty(self):
        assert gitconfig_user_block("", "") is None
        assert gitconfig_user_block("  \t", "\n\x00") is None

    def test_escapes_quotes_and_backslash(self):
        assert gitconfig_user_block('Foo\\bar"baz', "") == '[user]\n\tname = "Foo\\\\bar\\"baz"\n'

    def test_neutralizes_injection(self):
        block = gitconfig_user_block("Evil\n[core]\n\tsshCommand = touch /pwned", "a@b.com\x00")
        lines = block.splitlines()
        assert [ln for ln in lines if ln.startswith("[")] == ["[user]"]
        assert not any(ln.strip() == "[core]" for ln in lines)
        assert not any(ln.strip().startswith("sshCommand") for ln in lines)
        assert "\x00" not in block


class TestGitIdentityEnv:
    def test_both_sets_author_and_committer(self):
        assert git_identity_env("Mieszko", "m@example.com") == {
            "GIT_AUTHOR_NAME": "Mieszko",
            "GIT_COMMITTER_NAME": "Mieszko",
            "GIT_AUTHOR_EMAIL": "m@example.com",
            "GIT_COMMITTER_EMAIL": "m@example.com",
        }

    def test_email_only(self):
        assert git_identity_env("", "m@example.com") == {
            "GIT_AUTHOR_EMAIL": "m@example.com",
            "GIT_COMMITTER_EMAIL": "m@example.com",
        }

    def test_name_only(self):
        assert git_identity_env("Mieszko", "") == {
            "GIT_AUTHOR_NAME": "Mieszko",
            "GIT_COMMITTER_NAME": "Mieszko",
        }

    def test_empty(self):
        assert git_identity_env("", "") == {}
        assert git_identity_env("  \n", "\x00\t") == {}

    def test_values_are_cleaned_single_line(self):
        # No raw newlines reach the env (an env value with a newline is a footgun).
        env = git_identity_env("Mieszko\nEvil", "m@example.com\r")
        assert env["GIT_AUTHOR_NAME"] == "MieszkoEvil"
        assert "\n" not in env["GIT_AUTHOR_NAME"]
        assert env["GIT_AUTHOR_EMAIL"] == "m@example.com"
        # env values are NOT double-quoted (raw values, unlike the gitconfig file form)
        assert not env["GIT_AUTHOR_NAME"].startswith('"')
