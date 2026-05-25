"""Codex device-auth authentication strategy."""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from agento.framework.agent_manager.auth import (
    AuthenticationError,
    AuthResult,
    _run_cli,
)

_OPENAI_ISSUER = "https://auth.openai.com"


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except Exception as exc:
        raise AuthenticationError(f"Invalid JWT segment: {exc}") from exc


class CodexAuthStrategy:
    """Run ``codex auth login --device-auth`` in isolated HOME, extract credentials."""

    def authenticate(self, tmp_home: str, logger: logging.Logger) -> AuthResult:
        logger.info("Starting Codex device-auth login (follow the URL in your browser)...")
        _run_cli(["codex", "auth", "login", "--device-auth"], tmp_home, "Codex")

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

    def register_from_access_token(self, token: str) -> dict:
        """Validate a Codex/OpenAI access-token JWT and return the credentials
        dict that will be persisted as type='codex_access_token'.

        Validates JWT shape, issuer, and expiry; does NOT verify signature
        (Codex CLI does that on first use)."""
        if not isinstance(token, str) or token.count(".") != 2:
            raise AuthenticationError(
                "Access token is not a JWT (expected 3 dot-separated segments)."
            )
        _hdr, payload_b64, _sig = token.split(".")
        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except json.JSONDecodeError as exc:
            raise AuthenticationError(f"JWT payload is not valid JSON: {exc}") from exc

        iss = payload.get("iss")
        if iss != _OPENAI_ISSUER:
            raise AuthenticationError(
                f"Unexpected JWT issuer: {iss!r} (expected {_OPENAI_ISSUER!r})"
            )
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            raise AuthenticationError("JWT payload missing numeric 'exp' claim.")
        if exp <= time.time():
            raise AuthenticationError(f"Access token is already expired (exp={exp}).")

        return {"access_token": token, "expires_at": int(exp)}

    def register_from_api_key(self, key: str) -> dict:
        """Validate an OpenAI API key string and return the credentials dict
        that will be persisted as type='openai_api_key'."""
        if not isinstance(key, str) or not key.strip():
            raise AuthenticationError("OpenAI API key is empty.")
        stripped = key.strip()
        if stripped.startswith("sk-ant-"):
            raise AuthenticationError(
                "Refusing to register an Anthropic key (sk-ant-...) as an OpenAI key."
            )
        return {"api_key": stripped}
