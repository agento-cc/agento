from __future__ import annotations

import json

from agento.modules.claude.src.output_parser import parse_claude_output


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
