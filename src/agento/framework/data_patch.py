"""Data patch protocol and executor (Magento's DataPatchInterface equivalent).

Modules declare data patches in ``data_patch.json``.  Each patch class
implements :class:`DataPatch` — ``apply()`` for the work, ``require()`` for
ordering.  The executor resolves a topological order across all modules and
applies pending patches, tracking them in the ``data_patch`` table.
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import pymysql

from .module_loader import ModuleManifest, import_class

# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@runtime_checkable
class DataPatch(Protocol):
    """Protocol for module data patches."""

    def apply(self, conn: pymysql.Connection) -> None:
        """Execute the patch. Called once, tracked in ``data_patch``."""
        ...

    def require(self) -> list[str]:
        """Return fully-qualified patch names that must run before this one.

        Names use ``module/PatchName`` format (e.g. ``jira/PopulateDefaults``).
        Return an empty list if there are no dependencies.

        Magento equivalent: ``getDependencies()``.
        """
        ...


# ---------------------------------------------------------------------------
# Executor helpers
# ---------------------------------------------------------------------------

def get_applied_patches(conn: pymysql.Connection, module: str) -> set[str]:
    """Return set of patch names already applied for *module*."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM data_patch WHERE module = %s", (module,)
            )
            return {row["name"] for row in cur.fetchall()}
    except pymysql.err.ProgrammingError:
        # Table doesn't exist yet (before migrations run)
        return set()


def get_all_applied(conn: pymysql.Connection) -> set[str]:
    """Return set of fully-qualified ``module/name`` strings for all applied patches."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT module, name FROM data_patch")
            return {f"{row['module']}/{row['name']}" for row in cur.fetchall()}
    except pymysql.err.ProgrammingError:
        return set()


def get_all_pending(
    manifests: list[ModuleManifest],
    conn: pymysql.Connection,
) -> list[tuple[ModuleManifest, dict]]:
    """Collect pending patches from all modules.

    Returns ``(manifest, patch_decl)`` tuples for patches not yet applied.
    """
    applied = get_all_applied(conn)
    pending: list[tuple[ModuleManifest, dict]] = []
    for m in manifests:
        for p in m.data_patches.get("patches", []):
            fq_name = f"{m.name}/{p['name']}"
            if fq_name not in applied:
                pending.append((m, p))
    return pending


def resolve_patch_order(
    pending: list[tuple[ModuleManifest, dict]],
) -> list[tuple[ModuleManifest, dict]]:
    """Topological sort of pending patches by ``require()`` dependencies.

    Each patch class is imported and ``require()`` is called to discover
    dependencies.  Patches with no requirements maintain their original
    order (module dependency order from the caller).

    Raises ``CyclicPatchDependencyError`` if a cycle is detected.
    """
    if not pending:
        return []

    # Build lookup first (need full set before filtering requirements)
    fq_lookup: dict[str, tuple[ModuleManifest, dict]] = {}
    original_order: dict[str, int] = {}
    for i, (m, p) in enumerate(pending):
        fq = f"{m.name}/{p['name']}"
        fq_lookup[fq] = (m, p)
        original_order[fq] = i

    # Import classes and discover requirements
    requirements: dict[str, list[str]] = {}
    for fq, (m, p) in fq_lookup.items():
        cls = import_class(m.path, p["class"])
        instance = cls()
        reqs = instance.require()
        # Only track requirements that are in the pending set
        requirements[fq] = [r for r in reqs if r in fq_lookup]

    # Kahn's algorithm
    in_degree: dict[str, int] = {fq: 0 for fq in fq_lookup}
    for fq, reqs in requirements.items():
        in_degree[fq] = len(reqs)

    queue = sorted(
        [fq for fq, deg in in_degree.items() if deg == 0],
        key=lambda fq: original_order[fq],
    )

    result: list[tuple[ModuleManifest, dict]] = []
    while queue:
        fq = queue.pop(0)
        result.append(fq_lookup[fq])
        # Decrease in-degree for dependents
        for dep_fq, reqs in requirements.items():
            if fq in reqs:
                in_degree[dep_fq] -= 1
                if in_degree[dep_fq] == 0:
                    queue.append(dep_fq)
                    queue.sort(key=lambda f: original_order[f])

    if len(result) != len(fq_lookup):
        resolved = {f"{m.name}/{p['name']}" for m, p in result}
        unresolved = set(fq_lookup) - resolved
        raise CyclicPatchDependencyError(
            f"Cyclic dependency among data patches: {', '.join(sorted(unresolved))}"
        )

    return result


def apply_patch(
    manifest: ModuleManifest,
    patch_decl: dict,
    conn: pymysql.Connection,
    logger: logging.Logger,
) -> None:
    """Import, instantiate, and execute a data patch. Record in ``data_patch``."""
    cls = import_class(manifest.path, patch_decl["class"])
    instance = cls()
    instance.apply(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO data_patch (name, module) VALUES (%s, %s)",
            (patch_decl["name"], manifest.name),
        )
    conn.commit()
    logger.info("  [%s/%s] Data patch applied", manifest.name, patch_decl["name"])

    from .event_manager import get_event_manager
    from .events import DataPatchAppliedEvent

    get_event_manager().dispatch(
        "data_patch_apply_after",
        DataPatchAppliedEvent(name=patch_decl["name"], module=manifest.name),
    )


class CyclicPatchDependencyError(Exception):
    """Raised when data patches have circular dependencies."""
