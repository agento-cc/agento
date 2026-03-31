"""Module onboarding registry — modules contribute interactive onboarding via di.json."""
from __future__ import annotations

import logging
from typing import Protocol

import pymysql


class ModuleOnboarding(Protocol):
    def is_complete(self, conn: pymysql.Connection) -> bool:
        """Check if onboarding was already completed (config values present)."""
        ...

    def run(self, conn: pymysql.Connection, config: dict, logger: logging.Logger) -> None:
        """Execute the interactive onboarding flow."""
        ...

    def describe(self) -> str:
        """Human-readable one-liner of what this onboarding does."""
        ...


# Registry: module_name -> ModuleOnboarding instance
_ONBOARDINGS: dict[str, ModuleOnboarding] = {}


def register_onboarding(module_name: str, onboarding: ModuleOnboarding) -> None:
    """Register a module-contributed onboarding."""
    _ONBOARDINGS[module_name] = onboarding


def get_onboardings() -> dict[str, ModuleOnboarding]:
    """Return all registered onboardings."""
    return dict(_ONBOARDINGS)


def clear() -> None:
    """Reset registry (for testing)."""
    _ONBOARDINGS.clear()
