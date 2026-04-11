from __future__ import annotations

import json

import pytest

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
