"""Tests for agento doctor checks."""
from __future__ import annotations

import sys

from agento.framework.cli.doctor import _check_binary, _check_docker_compose, _check_python


class TestCheckPython:
    def test_current_python_is_ok(self):
        ok, info = _check_python()
        assert ok is True
        assert f"{sys.version_info.major}.{sys.version_info.minor}" in info


class TestCheckBinary:
    def test_found_binary(self):
        # python3 should always be available in test env
        ok, info = _check_binary("python3")
        assert ok is True
        assert info != "not found"

    def test_missing_binary(self):
        ok, info = _check_binary("nonexistent_binary_xyz_12345")
        assert ok is False
        assert info == "not found"


class TestCheckDockerCompose:
    def test_returns_tuple(self):
        ok, info = _check_docker_compose()
        assert isinstance(ok, bool)
        assert isinstance(info, str)
