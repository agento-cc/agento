"""Router registry — modules register routers via di.json."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .router import Router

_ROUTERS: list[tuple[int, str, object]] = []


def register_router(router: Router, order: int = 1000) -> None:
    """Register a router with a sort order. Lower order = higher priority."""
    _ROUTERS.append((order, router.name, router))
    _ROUTERS.sort(key=lambda entry: (entry[0], entry[1]))


def get_routers() -> list:
    """Return routers sorted by (order, name)."""
    return [router for _, _, router in _ROUTERS]


def clear() -> None:
    """Reset registry (for testing)."""
    _ROUTERS.clear()
