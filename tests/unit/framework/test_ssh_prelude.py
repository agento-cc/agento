"""Tests for the SSH prelude wrapper."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agento.framework.ssh_prelude import wrap_with_ssh_prelude


class TestWrapWithSshPrelude:
    def test_wraps_with_sh_c_and_sentinel(self):
        wrapped = wrap_with_ssh_prelude(["claude", "-p", "hi"])
        assert wrapped[0] == "sh"
        assert wrapped[1] == "-c"
        assert wrapped[3] == "--"
        assert wrapped[4:] == ["claude", "-p", "hi"]

    def test_prelude_contains_symlink_logic(self):
        wrapped = wrap_with_ssh_prelude(["x"])
        script = wrapped[2]
        assert 'ln -s "$HOME/.ssh"' in script
        assert "/root" in script
        assert "/home/agent" in script
        assert 'exec "$@"' in script


class TestPreludeExecution:
    """Drive the prelude with a real shell in a sandboxed tmp layout."""

    def test_exec_runs_command_without_home_ssh(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        env = {**os.environ, "HOME": str(home)}
        out = subprocess.check_output(
            wrap_with_ssh_prelude(["echo", "ok"]), env=env, text=True,
        )
        assert out.strip() == "ok"

    def test_prelude_creates_symlink_when_home_ssh_exists(self, tmp_path):
        home = tmp_path / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id_rsa").write_text("KEY")

        # Fake /root and /home/agent by overriding the loop vars via sh_prelude
        # clone: we can't rewrite /root in a test, but we can run the inner
        # logic against an explicit target list.
        pseudo_root = tmp_path / "pseudo_root"
        pseudo_root.mkdir()
        env = {**os.environ, "HOME": str(home), "_T": str(pseudo_root)}
        script = (
            '[ -d "$HOME/.ssh" ] && {'
            ' rm -rf "$_T/.ssh" 2>/dev/null;'
            ' ln -s "$HOME/.ssh" "$_T/.ssh" 2>/dev/null || true;'
            ' };'
            ' test -L "$_T/.ssh" && readlink "$_T/.ssh"'
        )
        out = subprocess.check_output(["sh", "-c", script], env=env, text=True)
        assert Path(out.strip()) == home / ".ssh"

    def test_prelude_is_noop_without_home_ssh(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        env = {**os.environ, "HOME": str(home)}
        out = subprocess.check_output(
            wrap_with_ssh_prelude(["sh", "-c", "test -d $HOME/.ssh && echo has || echo none"]),
            env=env, text=True,
        )
        assert out.strip() == "none"
