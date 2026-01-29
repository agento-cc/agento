"""Tests for router registry."""
from agento.framework.router import RoutingContext, RoutingResult
from agento.framework.router_registry import clear, get_routers, register_router


class _FakeRouter:
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def resolve(self, conn, context: RoutingContext) -> RoutingResult | None:
        return None


class TestRouterRegistry:
    def setup_method(self):
        clear()

    def teardown_method(self):
        clear()

    def test_register_and_get(self):
        r = _FakeRouter("test")
        register_router(r)
        assert get_routers() == [r]

    def test_ordering_by_order(self):
        r1 = _FakeRouter("b_router")
        r2 = _FakeRouter("a_router")
        register_router(r1, order=200)
        register_router(r2, order=100)
        routers = get_routers()
        assert routers[0].name == "a_router"
        assert routers[1].name == "b_router"

    def test_tie_breaking_by_name(self):
        r1 = _FakeRouter("beta")
        r2 = _FakeRouter("alpha")
        register_router(r1, order=100)
        register_router(r2, order=100)
        routers = get_routers()
        assert routers[0].name == "alpha"
        assert routers[1].name == "beta"

    def test_clear(self):
        register_router(_FakeRouter("test"))
        clear()
        assert get_routers() == []

    def test_empty_registry(self):
        assert get_routers() == []
