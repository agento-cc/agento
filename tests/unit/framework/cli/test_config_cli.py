"""Tests for config:set scope restriction enforcement (showIn* flags)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agento.framework.cli.config import _validate_config_path


@pytest.fixture
def fake_module(tmp_path: Path):
    module_dir = tmp_path / "testmod"
    module_dir.mkdir()
    (module_dir / "module.json").write_text(json.dumps({
        "name": "testmod",
        "tools": [
            {
                "name": "mytool",
                "fields": {
                    "api_key": {
                        "type": "string",
                        "label": "API Key",
                        "showInDefault": True,
                        "showInWorkspace": False,
                        "showInAgentView": False,
                    },
                    "region": {"type": "string", "label": "Region"},
                },
            }
        ],
    }))
    system = {
        "timezone": {
            "type": "string",
            "label": "IANA timezone",
            "showInDefault": True,
            "showInWorkspace": False,
            "showInAgentView": False,
        },
        "model": {"type": "string", "label": "Model"},
    }
    (module_dir / "system.json").write_text(json.dumps(system))
    return module_dir


class TestValidateConfigPathScope:
    def test_global_only_field_rejected_at_agent_view(self, fake_module, capsys):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            ok = _validate_config_path("testmod/timezone", scope="agent_view")
        assert ok is False
        out = capsys.readouterr().out
        assert "cannot be set at scope 'agent_view'" in out
        assert "default" in out

    def test_global_only_field_allowed_at_default(self, fake_module):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            assert _validate_config_path("testmod/timezone", scope="default") is True

    def test_field_without_flags_allowed_at_any_scope(self, fake_module):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            assert _validate_config_path("testmod/model", scope="default") is True
            assert _validate_config_path("testmod/model", scope="workspace") is True
            assert _validate_config_path("testmod/model", scope="agent_view") is True

    def test_default_scope_parameter_is_backward_compatible(self, fake_module):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            assert _validate_config_path("testmod/model") is True

    def test_unknown_field_still_rejected(self, fake_module, capsys):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            ok = _validate_config_path("testmod/nonexistent", scope="default")
        assert ok is False
        out = capsys.readouterr().out
        assert "not found" in out

    def test_unknown_module_rejected(self):
        with patch("agento.framework.core_config._find_module_dir", return_value=None):
            assert _validate_config_path("mystery/foo", scope="default") is False

    def test_tool_field_scope_restriction_enforced(self, fake_module, capsys):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            ok = _validate_config_path(
                "testmod/tools/mytool/api_key", scope="agent_view"
            )
        assert ok is False
        out = capsys.readouterr().out
        assert "cannot be set at scope 'agent_view'" in out

    def test_tool_field_without_flags_allowed_at_any_scope(self, fake_module):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            assert _validate_config_path(
                "testmod/tools/mytool/region", scope="agent_view"
            ) is True

    def test_tool_field_global_only_allowed_at_default(self, fake_module):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            assert _validate_config_path(
                "testmod/tools/mytool/api_key", scope="default"
            ) is True

    def test_unknown_tool_does_not_crash(self, fake_module):
        with patch("agento.framework.core_config._find_module_dir", return_value=fake_module):
            assert _validate_config_path(
                "testmod/tools/unknown_tool/field", scope="default"
            ) is True
