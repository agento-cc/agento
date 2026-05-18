from __future__ import annotations

from agento.framework.events import VerifyReason
from agento.framework.transcript_reader import ToolUse
from agento.modules.app_monitor.src.verify_mcp_usage import verify


def _t(name: str) -> ToolUse:
    return ToolUse(name=name, tool_use_id="toolu_x")


def test_pass_with_at_least_one_mcp_toolbox_call():
    assert verify([_t("Read"), _t("mcp__toolbox__jira_get_issue"), _t("Bash")]) is None


def test_veto_when_no_tool_uses_at_all():
    verdict = verify([])
    assert verdict is not None
    assert verdict.reason == VerifyReason.NO_MCP_CALLS
    assert verdict.retryable is True
    assert verdict.fresh_start is True


def test_veto_with_only_builtin_tools():
    verdict = verify([_t("Read"), _t("Bash"), _t("ToolSearch")])
    assert verdict is not None
    assert verdict.reason == VerifyReason.NO_MCP_CALLS


def test_veto_with_other_mcp_servers_but_not_toolbox():
    # mcp__context7__* is not toolbox — still a veto.
    verdict = verify([_t("mcp__context7__resolve-library-id"), _t("Read")])
    assert verdict is not None
    assert verdict.reason == VerifyReason.NO_MCP_CALLS


def test_veto_detail_mentions_prefix():
    verdict = verify([_t("Read")])
    assert verdict is not None
    assert "mcp__toolbox__" in (verdict.detail or "")
