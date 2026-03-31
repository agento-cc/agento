"""Tests for onboarding registry (follows commands.py pattern)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from agento.framework.onboarding import clear, get_onboardings, register_onboarding


class _FakeOnboarding:
    def __init__(self, complete: bool = False):
        self._complete = complete

    def is_complete(self, conn) -> bool:
        return self._complete

    def run(self, conn, config, logger) -> None:
        pass

    def describe(self) -> str:
        return "Fake onboarding"


class TestOnboardingRegistry:
    def setup_method(self):
        clear()

    def teardown_method(self):
        clear()

    def test_register_and_get(self):
        ob = _FakeOnboarding()
        register_onboarding("my_module", ob)

        result = get_onboardings()
        assert "my_module" in result
        assert result["my_module"] is ob

    def test_get_returns_copy(self):
        register_onboarding("mod_a", _FakeOnboarding())
        result = get_onboardings()
        result["mod_b"] = _FakeOnboarding()
        assert "mod_b" not in get_onboardings()

    def test_clear_empties_registry(self):
        register_onboarding("mod_a", _FakeOnboarding())
        clear()
        assert get_onboardings() == {}

    def test_overwrite_registration(self):
        ob1 = _FakeOnboarding()
        ob2 = _FakeOnboarding(complete=True)
        register_onboarding("mod_a", ob1)
        register_onboarding("mod_a", ob2)
        assert get_onboardings()["mod_a"] is ob2

    def test_is_complete_returns_false(self):
        ob = _FakeOnboarding(complete=False)
        assert ob.is_complete(MagicMock()) is False

    def test_is_complete_returns_true(self):
        ob = _FakeOnboarding(complete=True)
        assert ob.is_complete(MagicMock()) is True

    def test_describe(self):
        ob = _FakeOnboarding()
        assert ob.describe() == "Fake onboarding"
