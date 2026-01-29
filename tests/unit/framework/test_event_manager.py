"""Tests for EventManager — event-observer pattern."""

from __future__ import annotations

import pytest

from agento.framework.event_manager import (
    EventManager,
    ObserverEntry,
    clear,
    get_event_manager,
)


@pytest.fixture(autouse=True)
def _clean():
    clear()
    yield
    clear()


class _Recorder:
    """Observer that records calls."""

    calls: list = []  # noqa: RUF012

    def execute(self, event: object) -> None:
        _Recorder.calls.append(event)

    @classmethod
    def reset(cls):
        cls.calls = []


@pytest.fixture(autouse=True)
def _reset_recorder():
    _Recorder.reset()
    yield


class TestEventManager:
    def test_dispatch_no_observers(self):
        em = EventManager()
        em.dispatch("job_failed", {"some": "data"})  # no error

    def test_register_and_dispatch(self):
        em = EventManager()
        em.register("job_failed", ObserverEntry(name="rec", observer_class=_Recorder))
        em.dispatch("job_failed", "payload")
        assert _Recorder.calls == ["payload"]

    def test_deterministic_order_by_order_field(self):
        calls: list[str] = []

        class ObsA:
            def execute(self, event):
                calls.append("A")

        class ObsB:
            def execute(self, event):
                calls.append("B")

        em = EventManager()
        em.register("ev", ObserverEntry(name="b", observer_class=ObsB, order=200))
        em.register("ev", ObserverEntry(name="a", observer_class=ObsA, order=100))
        em.dispatch("ev", None)
        assert calls == ["A", "B"]

    def test_deterministic_order_by_name_when_same_order(self):
        calls: list[str] = []

        class ObsA:
            def execute(self, event):
                calls.append("A")

        class ObsB:
            def execute(self, event):
                calls.append("B")

        em = EventManager()
        em.register("ev", ObserverEntry(name="z_obs", observer_class=ObsB))
        em.register("ev", ObserverEntry(name="a_obs", observer_class=ObsA))
        em.dispatch("ev", None)
        assert calls == ["A", "B"]

    def test_observer_error_swallowed(self):
        calls: list[str] = []

        class BadObserver:
            def execute(self, event):
                raise RuntimeError("boom")

        class GoodObserver:
            def execute(self, event):
                calls.append("ok")

        em = EventManager()
        em.register("ev", ObserverEntry(name="bad", observer_class=BadObserver, order=1))
        em.register("ev", ObserverEntry(name="good", observer_class=GoodObserver, order=2))
        em.dispatch("ev", None)
        assert calls == ["ok"]

    def test_observer_count(self):
        em = EventManager()
        assert em.observer_count("ev") == 0
        em.register("ev", ObserverEntry(name="a", observer_class=_Recorder))
        assert em.observer_count("ev") == 1

    def test_mutable_event_data(self):
        """Observers can modify event data."""

        class Mutator:
            def execute(self, event):
                event["modified"] = True

        em = EventManager()
        em.register("ev", ObserverEntry(name="m", observer_class=Mutator))
        data = {"modified": False}
        em.dispatch("ev", data)
        assert data["modified"] is True


class TestRegistry:
    def test_get_event_manager_returns_same_instance(self):
        a = get_event_manager()
        b = get_event_manager()
        assert a is b

    def test_clear_resets_instance(self):
        a = get_event_manager()
        clear()
        b = get_event_manager()
        assert a is not b
