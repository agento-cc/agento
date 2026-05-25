"""Tests for CodexAuthStrategy register-from-X paths."""
from __future__ import annotations

import base64
import json
import time

import pytest

from agento.framework.agent_manager.errors import AuthenticationError
from agento.modules.codex.src.auth import CodexAuthStrategy


def _make_jwt(payload: dict, header: dict | None = None) -> str:
    header = header or {"alg": "RS256", "typ": "JWT"}

    def _b64(d: dict) -> str:
        raw = json.dumps(d, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{_b64(header)}.{_b64(payload)}.sig"


class TestRegisterFromAccessToken:
    def test_returns_minimal_credentials_dict(self):
        exp = int(time.time()) + 86_400
        token = _make_jwt({"iss": "https://auth.openai.com", "exp": exp})
        result = CodexAuthStrategy().register_from_access_token(token)
        assert result == {"access_token": token, "expires_at": exp}

    def test_rejects_non_three_segment(self):
        with pytest.raises(AuthenticationError, match="JWT"):
            CodexAuthStrategy().register_from_access_token("not.a.jwt.token")

    def test_rejects_undecodable_payload(self):
        with pytest.raises(AuthenticationError):
            CodexAuthStrategy().register_from_access_token("aaa.@@@.sig")

    def test_rejects_expired(self):
        token = _make_jwt({"iss": "https://auth.openai.com", "exp": int(time.time()) - 60})
        with pytest.raises(AuthenticationError, match="expired"):
            CodexAuthStrategy().register_from_access_token(token)

    def test_rejects_wrong_issuer(self):
        token = _make_jwt({"iss": "https://evil.example.com", "exp": int(time.time()) + 86400})
        with pytest.raises(AuthenticationError, match="issuer"):
            CodexAuthStrategy().register_from_access_token(token)

    def test_rejects_missing_exp(self):
        token = _make_jwt({"iss": "https://auth.openai.com"})
        with pytest.raises(AuthenticationError, match="exp"):
            CodexAuthStrategy().register_from_access_token(token)


class TestRegisterFromApiKey:
    def test_accepts_sk_prefix(self):
        result = CodexAuthStrategy().register_from_api_key("sk-proj-abc123")
        assert result == {"api_key": "sk-proj-abc123"}

    def test_rejects_empty(self):
        with pytest.raises(AuthenticationError):
            CodexAuthStrategy().register_from_api_key("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(AuthenticationError):
            CodexAuthStrategy().register_from_api_key("   ")

    def test_rejects_obvious_non_openai_prefix(self):
        """Anthropic keys (sk-ant-...) must not be accepted as OpenAI keys."""
        with pytest.raises(AuthenticationError, match="OpenAI"):
            CodexAuthStrategy().register_from_api_key("sk-ant-XXXX")

    def test_strips_surrounding_whitespace(self):
        result = CodexAuthStrategy().register_from_api_key("  sk-proj-abc  ")
        assert result == {"api_key": "sk-proj-abc"}
