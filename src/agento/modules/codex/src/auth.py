"""Codex device-code authentication strategy."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from agento.framework.agent_manager.auth import (
    AuthenticationError,
    AuthResult,
    _run_cli,
)


class CodexAuthStrategy:
    """Run ``codex auth login --device-code`` in isolated HOME, extract credentials."""

    def authenticate(self, tmp_home: str, logger: logging.Logger) -> AuthResult:
        logger.info("Starting Codex device-code login (follow the URL in your browser)...")
        _run_cli(["codex", "auth", "login", "--device-code"], tmp_home, "Codex")

        creds_path = Path(tmp_home) / ".codex" / "auth.json"
        if not creds_path.is_file():
            raise AuthenticationError(
                "Codex login completed but auth.json not found. "
                "Auth may have been cancelled."
            )

        raw = json.loads(creds_path.read_text())
        tokens = raw.get("tokens", {})
        access_token = tokens.get("access_token")
        if not access_token:
            raise AuthenticationError(
                "Codex auth.json exists but contains no access_token. "
                "Auth may have been incomplete."
            )

        return AuthResult(
            subscription_key=access_token,
            refresh_token=tokens.get("refresh_token"),
            expires_at=None,
            subscription_type=None,
            id_token=tokens.get("id_token"),
            raw_auth=raw,
        )
