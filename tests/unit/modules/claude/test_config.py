"""Tests for ClaudeConfigWriter — .claude.json, .claude/settings.json, .mcp.json."""
from __future__ import annotations

import json

import pytest

from agento.modules.claude.src.config import ClaudeConfigWriter


@pytest.fixture
def writer():
    return ClaudeConfigWriter()


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "workspace" / "main" / "alpha"
    d.mkdir(parents=True)
    return d


class TestPrepareWorkspace:
    TOOLBOX = "http://toolbox:3001"

    def test_generates_claude_json_with_model(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "opus-4"}, toolbox_url=self.TOOLBOX)
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["model"] == "opus-4"

    def test_generates_system_prompt(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"model": "sonnet", "claude/personality": "Be concise."},
            toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["systemPrompt"] == "Be concise."

    def test_generates_permissions(self, writer, work_dir):
        perms = '{"allow": ["Read", "Write"]}'
        writer.prepare_workspace(
            work_dir, {"claude/permissions": perms}, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".claude.json").read_text())
        assert data["permissions"] == {"allow": ["Read", "Write"]}

    def test_skips_invalid_permissions_json(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"model": "opus", "claude/permissions": "not-json{"},
            toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".claude.json").read_text())
        assert "permissions" not in data

    def test_generates_settings_json_full_trust(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"claude/trust_level": "full"}, toolbox_url=self.TOOLBOX,
        )
        settings_path = work_dir / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["permissions"]["dangerouslySkipPermissions"] is True

    def test_trust_level_not_full(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"claude/trust_level": "limited"}, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".claude" / "settings.json").read_text())
        assert data["permissions"]["dangerouslySkipPermissions"] is False

    def test_empty_config_still_writes_toolbox_mcp(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {}, toolbox_url=self.TOOLBOX)
        assert not (work_dir / ".claude.json").exists()
        assert not (work_dir / ".claude" / "settings.json").exists()
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse"

    def test_extras_merge_with_toolbox_mcp(self, writer, work_dir):
        extras = '{"other": {"command": "npx", "args": ["-y", "server"]}}'
        writer.prepare_workspace(
            work_dir, {"mcp/servers": extras}, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert set(data["mcpServers"].keys()) == {"toolbox", "other"}

    def test_always_writes_toolbox_when_no_extras(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {"model": "opus"}, toolbox_url=self.TOOLBOX)
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse"

    def test_ignores_invalid_extras_json(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {"mcp/servers": "not-json{"}, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert list(data["mcpServers"].keys()) == ["toolbox"]

    def test_appends_agent_view_id_to_toolbox_sse_url(self, writer, work_dir):
        writer.prepare_workspace(
            work_dir, {}, agent_view_id=2, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse?agent_view_id=2"

    def test_no_agent_view_id_leaves_url_unchanged(self, writer, work_dir):
        writer.prepare_workspace(work_dir, {}, toolbox_url=self.TOOLBOX)
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == "http://toolbox:3001/sse"

    def test_does_not_modify_non_mcp_urls(self, writer, work_dir):
        servers = '{"other": {"type": "stdio", "command": "node"}}'
        writer.prepare_workspace(
            work_dir, {"mcp/servers": servers},
            agent_view_id=5, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "url" not in data["mcpServers"]["other"]

    def test_injects_into_any_sse_or_mcp_url(self, writer, work_dir):
        servers = '{"other": {"type": "sse", "url": "http://other:4000/sse"}}'
        writer.prepare_workspace(
            work_dir, {"mcp/servers": servers},
            agent_view_id=5, toolbox_url=self.TOOLBOX,
        )
        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "agent_view_id=5" in data["mcpServers"]["other"]["url"]


class TestInjectRuntimeParams:
    def test_appends_params_to_mcp_json(self, writer, work_dir):
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/sse?agent_view_id=2"}}}
        (work_dir / ".mcp.json").write_text(json.dumps(mcp))

        writer.inject_runtime_params(work_dir, job_id=10)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert data["mcpServers"]["toolbox"]["url"] == (
            "http://toolbox:3001/sse?agent_view_id=2&job_id=10"
        )

    def test_noop_when_no_mcp_json(self, writer, work_dir):
        writer.inject_runtime_params(work_dir, job_id=10)
        assert not (work_dir / ".mcp.json").exists()

    def test_handles_mcp_url(self, writer, work_dir):
        mcp = {"mcpServers": {"toolbox": {"url": "http://toolbox:3001/mcp?agent_view_id=2"}}}
        (work_dir / ".mcp.json").write_text(json.dumps(mcp))

        writer.inject_runtime_params(work_dir, job_id=5)

        data = json.loads((work_dir / ".mcp.json").read_text())
        assert "job_id=5" in data["mcpServers"]["toolbox"]["url"]


class TestWriteCredentials:
    def test_writes_credentials_json_in_claude_ai_oauth_format(self, writer, work_dir):
        creds = {
            "subscription_key": "sk-ant-oat01-xyz",
            "refresh_token": "rt-123",
            "expires_at": 1799999999,
            "subscription_type": "team",
            "id_token": "ignored",
            "raw_auth": "ignored",
        }
        writer.write_credentials(work_dir, creds)

        path = work_dir / ".claude" / ".credentials.json"
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data == {
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-xyz",
                "refreshToken": "rt-123",
                "expiresAt": 1799999999,
                "subscriptionType": "team",
            }
        }
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_skips_when_no_subscription_key(self, writer, work_dir):
        writer.write_credentials(work_dir, {"refresh_token": "x"})
        assert not (work_dir / ".claude" / ".credentials.json").exists()

    def test_optional_fields_become_null(self, writer, work_dir):
        writer.write_credentials(work_dir, {"subscription_key": "sk-x"})
        data = json.loads((work_dir / ".claude" / ".credentials.json").read_text())
        oauth = data["claudeAiOauth"]
        assert oauth["accessToken"] == "sk-x"
        assert oauth["refreshToken"] is None
        assert oauth["expiresAt"] is None
        assert oauth["subscriptionType"] is None

    def test_preserves_scopes_and_rate_limit_tier_from_raw_auth(self, writer, work_dir):
        raw_creds = {
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-abc",
                "refreshToken": "sk-ant-ort01-def",
                "expiresAt": 1776946615316,
                "scopes": [
                    "user:file_upload",
                    "user:inference",
                    "user:mcp_servers",
                    "user:profile",
                    "user:sessions:claude_code",
                ],
                "subscriptionType": "team",
                "rateLimitTier": "default_claude_max_5x",
            }
        }
        creds = {
            "subscription_key": "sk-ant-oat01-abc",
            "refresh_token": "sk-ant-ort01-def",
            "expires_at": 1776946615316,
            "subscription_type": "team",
            "raw_auth": {"credentials": raw_creds, "claude_json": {}},
        }
        writer.write_credentials(work_dir, creds)

        data = json.loads((work_dir / ".claude" / ".credentials.json").read_text())
        assert data == raw_creds

    def test_writes_claude_json_with_oauth_account(self, writer, work_dir):
        claude_json = {
            "oauthAccount": {
                "emailAddress": "mklauza@company.com",
                "organizationName": "My company",
            },
            "numStartups": 3,
            "userID": "abc123",
        }
        creds = {
            "subscription_key": "sk-x",
            "raw_auth": {
                "credentials": {"claudeAiOauth": {"accessToken": "sk-x"}},
                "claude_json": claude_json,
            },
        }
        writer.write_credentials(work_dir, creds)

        out = json.loads((work_dir / ".claude.json").read_text())
        assert out["oauthAccount"]["emailAddress"] == "mklauza@company.com"
        assert out["numStartups"] == 3
        assert out["userID"] == "abc123"

    def test_merges_claude_json_with_existing_workspace_config(self, writer, work_dir):
        # prepare_workspace has already run and wrote agent_view-level config
        (work_dir / ".claude.json").write_text(json.dumps({
            "model": "opus-4-7",
            "systemPrompt": "Be concise.",
            "permissions": {"allow": ["Read"]},
        }))

        creds = {
            "subscription_key": "sk-x",
            "raw_auth": {
                "credentials": {"claudeAiOauth": {"accessToken": "sk-x"}},
                "claude_json": {
                    "oauthAccount": {"emailAddress": "m@k.com"},
                    "userID": "abc",
                },
            },
        }
        writer.write_credentials(work_dir, creds)

        out = json.loads((work_dir / ".claude.json").read_text())
        # agent_view config survives
        assert out["model"] == "opus-4-7"
        assert out["systemPrompt"] == "Be concise."
        assert out["permissions"] == {"allow": ["Read"]}
        # oauth state added
        assert out["oauthAccount"] == {"emailAddress": "m@k.com"}
        assert out["userID"] == "abc"

    def test_auth_state_wins_over_stale_build_claude_json(self, writer, work_dir):
        # Simulate Claude having written stale first-run state in a prior build
        (work_dir / ".claude.json").write_text(json.dumps({
            "userID": "old-fingerprint",
            "numStartups": 1,
        }))

        creds = {
            "subscription_key": "sk-x",
            "raw_auth": {
                "credentials": {"claudeAiOauth": {"accessToken": "sk-x"}},
                "claude_json": {
                    "userID": "new-fingerprint",
                    "numStartups": 5,
                    "oauthAccount": {"emailAddress": "m@k.com"},
                },
            },
        }
        writer.write_credentials(work_dir, creds)

        out = json.loads((work_dir / ".claude.json").read_text())
        assert out["userID"] == "new-fingerprint"
        assert out["numStartups"] == 5
        assert out["oauthAccount"] == {"emailAddress": "m@k.com"}

    def test_skips_claude_json_when_raw_auth_missing(self, writer, work_dir):
        writer.write_credentials(work_dir, {"subscription_key": "sk-x"})
        assert not (work_dir / ".claude.json").exists()

    def test_skips_claude_json_when_claude_json_empty(self, writer, work_dir):
        creds = {
            "subscription_key": "sk-x",
            "raw_auth": {
                "credentials": {"claudeAiOauth": {"accessToken": "sk-x"}},
                "claude_json": {},
            },
        }
        writer.write_credentials(work_dir, creds)
        assert not (work_dir / ".claude.json").exists()

    def test_non_dict_raw_auth_falls_back_to_legacy_fields(self, writer, work_dir):
        # Old rows stored before raw_auth capture: raw_auth may be a string or None.
        creds = {
            "subscription_key": "sk-legacy",
            "refresh_token": "rt-legacy",
            "expires_at": 1799999999,
            "subscription_type": "team",
            "raw_auth": "ignored-string",
        }
        writer.write_credentials(work_dir, creds)

        data = json.loads((work_dir / ".claude" / ".credentials.json").read_text())
        assert data == {
            "claudeAiOauth": {
                "accessToken": "sk-legacy",
                "refreshToken": "rt-legacy",
                "expiresAt": 1799999999,
                "subscriptionType": "team",
            }
        }
        assert not (work_dir / ".claude.json").exists()


class TestOwnedPaths:
    def test_returns_claude_files_and_dir(self, writer):
        files, dirs = writer.owned_paths()
        assert files == {".claude.json", ".mcp.json"}
        assert dirs == {".claude"}


class TestMigrateLegacyWorkspaceConfig:
    def test_merges_enabled_mcp_servers_from_legacy_settings_local(self, writer, work_dir, tmp_path):
        build_settings_dir = work_dir / ".claude"
        build_settings_dir.mkdir(parents=True)
        (build_settings_dir / "settings.local.json").write_text(
            json.dumps({"enabledMcpjsonServers": ["other"]})
        )

        workspace_root = tmp_path / "workspace"
        legacy_settings_dir = workspace_root / ".claude"
        legacy_settings_dir.mkdir(parents=True)
        (legacy_settings_dir / "settings.local.json").write_text(
            json.dumps({"enabledMcpjsonServers": ["toolbox"]})
        )

        writer.migrate_legacy_workspace_config(work_dir, workspace_root)

        data = json.loads((build_settings_dir / "settings.local.json").read_text())
        assert data["enabledMcpjsonServers"] == ["toolbox", "other"]
