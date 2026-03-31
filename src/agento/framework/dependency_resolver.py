"""Module dependency resolver — topological sort by sequence, then order.

Naming follows Magento convention:
  - ``sequence``: list of module names this module depends on (Magento ``<sequence>``)
  - ``order``: integer sort position within same dependency tier (lower = earlier)
"""
from __future__ import annotations

import logging
from collections import defaultdict

from .module_loader import ModuleManifest

logger = logging.getLogger(__name__)


class CyclicDependencyError(Exception):
    """Raised when modules form a dependency cycle."""


class DisabledDependencyError(Exception):
    """Raised when an enabled module depends on a disabled module."""


def validate_dependencies(
    enabled: list[ModuleManifest], all_scanned: list[ModuleManifest]
) -> None:
    """Validate that all sequence deps of enabled modules are also enabled.

    Raises DisabledDependencyError if a disabled module is required by an enabled one.
    Missing-on-disk deps are ignored (handled by resolve_order skip logic).
    """
    enabled_names = {m.name for m in enabled}
    all_names = {m.name for m in all_scanned}

    for m in enabled:
        for dep in m.sequence:
            if dep in all_names and dep not in enabled_names:
                raise DisabledDependencyError(
                    f"Module '{m.name}' requires '{dep}', but '{dep}' is disabled. "
                    f"Enable it with: agento module:enable {dep}"
                )


def resolve_order(manifests: list[ModuleManifest]) -> list[ModuleManifest]:
    """Sort modules respecting sequence (dependencies) and order (sort position).

    Uses Kahn's algorithm for topological sort.
    Modules with unresolvable dependencies are warned and skipped.
    """
    by_name: dict[str, ModuleManifest] = {m.name: m for m in manifests}
    available = set(by_name.keys())

    # Validate dependencies — skip modules with missing deps
    valid: dict[str, ModuleManifest] = {}
    skipped: set[str] = set()

    # Iteratively remove modules whose deps cannot be satisfied
    changed = True
    remaining = dict(by_name)
    while changed:
        changed = False
        for name, m in list(remaining.items()):
            missing = [dep for dep in m.sequence if dep not in available - skipped]
            if missing:
                logger.warning(
                    "Module %r skipped: unmet dependencies %s", name, missing
                )
                skipped.add(name)
                del remaining[name]
                changed = True

    valid = remaining

    if not valid:
        return []

    # Build adjacency for topological sort
    in_degree: dict[str, int] = defaultdict(int)
    dependents: dict[str, list[str]] = defaultdict(list)

    for name, m in valid.items():
        in_degree.setdefault(name, 0)
        for dep in m.sequence:
            if dep in valid:
                dependents[dep].append(name)
                in_degree[name] += 1

    # Kahn's algorithm with (order, name) sorting for determinism
    queue: list[str] = sorted(
        [n for n, d in in_degree.items() if d == 0],
        key=lambda n: (valid[n].order, n),
    )
    result: list[ModuleManifest] = []

    while queue:
        current = queue.pop(0)
        result.append(valid[current])
        for dep in sorted(dependents[current]):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
        # Re-sort queue to maintain (order, name) determinism
        queue.sort(key=lambda n: (valid[n].order, n))

    if len(result) != len(valid):
        resolved_names = {m.name for m in result}
        cycle_names = [n for n in valid if n not in resolved_names]
        raise CyclicDependencyError(
            f"Cyclic dependency detected among modules: {cycle_names}"
        )

    return result
