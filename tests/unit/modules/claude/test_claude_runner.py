from __future__ import annotations

import json

import pytest

from agento.framework.runner import McpInitReport, McpServerStatus
from agento.modules.claude.src.output_parser import (
    AuthenticationError,
    parse_claude_output,
)

# ---- Legacy single JSON format (backward compat) ----

def test_parse_output_success(claude_success):
    raw = json.dumps(claude_success)
    result = parse_claude_output(raw)

    assert result.input_tokens == 1500
    assert result.output_tokens == 800
    assert result.cost_usd == 0.0123
    assert result.num_turns == 3
    assert result.duration_ms == 45000
    assert result.subtype == "success"


def test_parse_output_invalid_json():
    result = parse_claude_output("this is not json at all")

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.cost_usd is None
    assert result.raw_output == "this is not json at all"


def test_parse_output_partial_data():
    raw = json.dumps({"usage": {"input_tokens": 100}})
    result = parse_claude_output(raw)

    assert result.input_tokens == 100
    assert result.output_tokens is None
    assert result.cost_usd is None


def test_stats_line_full(claude_success):
    raw = json.dumps(claude_success)
    result = parse_claude_output(raw)
    line = result.stats_line
    assert "turns=3" in line
    assert "in=1500" in line
    assert "out=800" in line
    assert "cost_usd=0.0123" in line
    assert "duration_ms=45000" in line


def test_stats_line_missing_data():
    result = parse_claude_output("bad data")
    line = result.stats_line
    assert "turns=?" in line
    assert "in=?" in line


# ---- Stream-JSON format ----

def test_parse_stream_json_result_event():
    raw = (
        '{"type": "init", "session_id": "sess-abc"}\n'
        '{"type": "assistant", "message": "working..."}\n'
        '{"type": "result", "result": "done", "is_error": false, '
        '"usage": {"input_tokens": 200, "output_tokens": 100}, '
        '"total_cost_usd": 0.01, "num_turns": 2, "duration_ms": 3000, '
        '"session_id": "sess-abc"}\n'
    )
    result = parse_claude_output(raw)

    assert result.input_tokens == 200
    assert result.output_tokens == 100
    assert result.cost_usd == 0.01
    assert result.num_turns == 2
    assert result.duration_ms == 3000
    assert result.subtype == "sess-abc"


def test_parse_stream_json_session_id_from_init():
    raw = (
        '{"type": "init", "session_id": "sess-init"}\n'
        '{"type": "result", "result": "ok", "usage": {"input_tokens": 10, "output_tokens": 5}}\n'
    )
    result = parse_claude_output(raw)

    assert result.subtype == "sess-init"
    assert result.input_tokens == 10


def test_parse_stream_json_error_event():
    raw = (
        '{"type": "init", "session_id": "sess-err"}\n'
        '{"type": "result", "result": "something went wrong", "is_error": true}\n'
    )
    with pytest.raises(RuntimeError, match="something went wrong"):
        parse_claude_output(raw)


def test_parse_stream_json_auth_error():
    raw = (
        '{"type": "result", "result": "authentication_error: invalid token", "is_error": true}\n'
    )
    with pytest.raises(AuthenticationError, match="authentication_error"):
        parse_claude_output(raw)


def test_parse_stream_json_partial_output_with_session():
    """Partial output from timeout -- only init event, no result."""
    raw = '{"type": "init", "session_id": "sess-partial"}\n'
    result = parse_claude_output(raw)

    assert result.subtype == "sess-partial"
    assert result.input_tokens is None


def test_parse_stream_json_no_result_event():
    """No recognizable events -- fallback."""
    raw = "some random text\nnot json lines\n"
    result = parse_claude_output(raw)

    assert result.raw_output == raw
    assert result.input_tokens is None


# ---- MCP init self-report (system/init line) ----

def _result_line(session_id: str = "sess-mcp") -> str:
    return (
        '{"type": "result", "result": "ok", "is_error": false, '
        '"usage": {"input_tokens": 10, "output_tokens": 5}, '
        f'"session_id": "{session_id}"}}\n'
    )


def test_parse_claude_output_extracts_mcp_init():
    raw = (
        '{"type": "system", "subtype": "init", "session_id": "sess-mcp", '
        '"mcp_servers": [{"name": "toolbox", "status": "connected"}, '
        '{"name": "context7", "status": "failed"}]}\n'
        + _result_line()
    )
    result = parse_claude_output(raw)

    assert result.mcp_init == McpInitReport(
        servers=(
            McpServerStatus("toolbox", "connected"),
            McpServerStatus("context7", "failed"),
        )
    )


def test_parse_claude_output_empty_servers_list():
    raw = (
        '{"type": "system", "subtype": "init", "mcp_servers": []}\n'
        + _result_line()
    )
    result = parse_claude_output(raw)

    # Empty list IS a valid init report ("started, no MCP servers visible"),
    # NOT the same as "no init at all".
    assert result.mcp_init == McpInitReport(servers=())
    assert result.mcp_init is not None


def test_parse_claude_output_no_init_event():
    raw = _result_line()
    result = parse_claude_output(raw)

    assert result.mcp_init is None


def test_parse_claude_output_malformed_init_skipped():
    # Server entry missing "status" -> whole report untrusted, no exception.
    raw = (
        '{"type": "system", "subtype": "init", '
        '"mcp_servers": [{"name": "toolbox"}]}\n'
        + _result_line()
    )
    result = parse_claude_output(raw)

    assert result.mcp_init is None


def test_parse_claude_output_only_first_init_wins():
    raw = (
        '{"type": "system", "subtype": "init", '
        '"mcp_servers": [{"name": "toolbox", "status": "connected"}]}\n'
        '{"type": "system", "subtype": "init", '
        '"mcp_servers": [{"name": "context7", "status": "failed"}]}\n'
        + _result_line()
    )
    result = parse_claude_output(raw)

    assert result.mcp_init == McpInitReport(
        servers=(McpServerStatus("toolbox", "connected"),)
    )


def test_parse_claude_output_mcp_init_survives_missing_result_event():
    # Partial output (timeout): init line present, no result event.
    raw = (
        '{"type": "system", "subtype": "init", "session_id": "sess-x", '
        '"mcp_servers": [{"name": "toolbox", "status": "connected"}]}\n'
    )
    result = parse_claude_output(raw)

    assert result.subtype == "sess-x"
    assert result.mcp_init == McpInitReport(
        servers=(McpServerStatus("toolbox", "connected"),)
    )
