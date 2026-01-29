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
    """Run ``claude auth login`` in isolated HOME, extract credentials."""

    def authenticate(self, tmp_home: str, logger: logging.Logger) -> AuthResult:
        logger.info("Starting Claude OAuth login (follow the URL in your browser)...")
        _run_cli(["claude", "auth", "login"], tmp_home, "Claude")

        creds_path = Path(tmp_home) / ".claude" / ".credentials.json"
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

        return AuthResult(
            subscription_key=access_token,
            refresh_token=oauth.get("refreshToken"),
            expires_at=oauth.get("expiresAt"),
            subscription_type=oauth.get("subscriptionType"),
        )
