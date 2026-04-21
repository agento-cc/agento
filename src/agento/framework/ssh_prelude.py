"""Shell prelude that makes OpenSSH/git find the build dir's materialized `.ssh/`.

OpenSSH resolves ``~/.ssh/`` via ``getpwuid(getuid())->pw_dir``, not ``$HOME``.
Setting ``HOME=<build_dir>`` on the agent process is not enough — the passwd
home (``/root`` for root, ``/home/agent`` for the agent user) must also point
at the build dir's ``.ssh/``. We do that with a symlink established by a short
shell prelude that runs in-process before ``exec``-ing the agent CLI.
"""
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
    """Return ``["sh", "-c", <prelude>, "--", *cmd]``.

    The ``--`` becomes ``$0`` inside the prelude; ``$@`` is the original command.
    """
    return ["sh", "-c", _PRELUDE, "--", *cmd]
