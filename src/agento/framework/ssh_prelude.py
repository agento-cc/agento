# OpenSSH resolves ~/.ssh/ via getpwuid()->pw_dir, not $HOME — symlink passwd home to build .ssh/.
from __future__ import annotations

_PRELUDE = (
    '[ -d "$HOME/.ssh" ] && {'
    ' for _t in /root /home/agent; do'
    ' [ "$_t" = "$HOME" ] && continue;'
    ' [ -d "$_t" ] || continue;'
    ' rm -rf "$_t/.ssh" 2>/dev/null;'
    ' ln -s "$HOME/.ssh" "$_t/.ssh" 2>/dev/null || true;'
    ' done;'
    ' };'
    ' exec "$@"'
)


def wrap_with_ssh_prelude(cmd: list[str]) -> list[str]:
    return ["sh", "-c", _PRELUDE, "--", *cmd]
