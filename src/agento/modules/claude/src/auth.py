"""Claude OAuth authentication strategy."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from agento.framework.agent_manager.auth import (
    AuthenticationError,
    AuthResult,
    _run_cli,
)


class ClaudeAuthStrategy:
    """Run ``claude auth login`` with the user's real HOME.

    Claude CLI's OAuth polling depends on state in ``$HOME/.claude/``.
    An isolated temp HOME breaks the polling, so we ignore ``tmp_home``
    and use the real HOME for the CLI process.
    """

    def authenticate(self, tmp_home: str, logger: logging.Logger) -> AuthResult:
        logger.info("Starting Claude OAuth login (follow the URL in your browser)...")
        # Run full `claude` TUI (not `claude auth login`) — only the TUI
        # has the "Paste code here" prompt needed for headless/Docker auth.
        # Use real HOME because Claude CLI's OAuth polling needs $HOME/.claude/.
        real_home = str(Path.home())
        _run_cli(["claude"], real_home, "Claude")

        creds_path = Path(real_home) / ".claude" / ".credentials.json"
        if not creds_path.is_file():
            raise AuthenticationError(
                "Claude login completed but credentials file not found. "
                "Auth may have been cancelled."
            )

        raw = json.loads(creds_path.read_text())
        oauth = raw.get("claudeAiOauth", {})
        access_token = oauth.get("accessToken")
        if not access_token:
            raise AuthenticationError(
                "Credentials file exists but contains no accessToken. "
                "Auth may have been incomplete."
            )

        # Claude Code stores its login state in TWO places:
        # - ``~/.claude/.credentials.json`` (oauth tokens; seen above)
        # - ``~/.claude.json`` at HOME root (``oauthAccount`` + per-install user state)
        # Without the second, a sandboxed Claude with HOME=<build dir> sees creds but
        # still falls through to the login picker. Capture both so ``write_credentials``
        # can restore them verbatim.
        claude_json_path = Path(real_home) / ".claude.json"
        claude_json: dict = {}
        if claude_json_path.is_file():
            try:
                claude_json = json.loads(claude_json_path.read_text())
                if not isinstance(claude_json, dict):
                    claude_json = {}
            except (json.JSONDecodeError, OSError):
                claude_json = {}

        return AuthResult(
            subscription_key=access_token,
            refresh_token=oauth.get("refreshToken"),
            expires_at=oauth.get("expiresAt"),
            subscription_type=oauth.get("subscriptionType"),
            raw_auth={
                "credentials": raw,
                "claude_json": claude_json,
            },
        )
