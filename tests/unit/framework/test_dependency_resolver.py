"""Tests for dependency_resolver — topological sort by sequence + order."""
from pathlib import Path

import pytest

from agento.framework.dependency_resolver import (
    CyclicDependencyError,
    DisabledDependencyError,
    get_transitive_dependents,
    resolve_order,
    validate_dependencies,
)
from agento.framework.module_loader import ModuleManifest


def _m(name: str, *, sequence: list[str] | None = None, order: int = 1000) -> ModuleManifest:
    """Shorthand to create a minimal ModuleManifest."""
    return ModuleManifest(
        name=name,
        version="1.0.0",
        description="",
        path=Path(f"/fake/{name}"),
        sequence=sequence or [],
        order=order,
    )


class TestResolveOrderNoDeps:
    """Modules without dependencies sort by order, then name."""

    def test_single_module(self):
        result = resolve_order([_m("a")])
        assert [m.name for m in result] == ["a"]

    def test_sorted_by_order(self):
        modules = [_m("z", order=100), _m("a", order=200)]
        result = resolve_order(modules)
        assert [m.name for m in result] == ["z", "a"]

    def test_same_order_sorted_by_name(self):
        modules = [_m("b"), _m("a"), _m("c")]
        result = resolve_order(modules)
        assert [m.name for m in result] == ["a", "b", "c"]

    def test_empty(self):
        assert resolve_order([]) == []

    def test_real_modules_order(self):
        """Matches actual module.json order values: jira=100, claude=200, codex=200."""
        modules = [
            _m("codex", order=200),
            _m("jira", order=100),
            _m("claude", order=200),
        ]
        result = resolve_order(modules)
        assert [m.name for m in result] == ["jira", "claude", "codex"]


class TestResolveOrderWithDeps:
    """Modules with sequence (dependencies) load after their deps."""

    def test_linear_dependency(self):
        modules = [
            _m("b", sequence=["a"], order=100),
            _m("a", order=200),
        ]
        result = resolve_order(modules)
        assert [m.name for m in result] == ["a", "b"]

    def test_diamond_dependency(self):
        """A -> B, A -> C, B -> D, C -> D (D must come first)."""
        modules = [
            _m("a", sequence=["b", "c"]),
            _m("b", sequence=["d"]),
            _m("c", sequence=["d"]),
            _m("d"),
        ]
        result = resolve_order(modules)
        names = [m.name for m in result]
        assert names.index("d") < names.index("b")
        assert names.index("d") < names.index("c")
        assert names.index("b") < names.index("a")
        assert names.index("c") < names.index("a")

    def test_order_within_tier(self):
        """B and C both depend on A; C has lower order so comes first."""
        modules = [
            _m("a", order=1000),
            _m("b", sequence=["a"], order=200),
            _m("c", sequence=["a"], order=100),
        ]
        result = resolve_order(modules)
        names = [m.name for m in result]
        assert names[0] == "a"
        assert names.index("c") < names.index("b")


class TestResolveOrderMissingDeps:
    """Missing dependencies: warn and skip the dependent module."""

    def test_missing_dep_skipped(self):
        modules = [_m("a", sequence=["nonexistent"]), _m("b")]
        result = resolve_order(modules)
        assert [m.name for m in result] == ["b"]

    def test_cascading_skip(self):
        """If A is skipped (missing dep), B depending on A is also skipped."""
        modules = [
            _m("a", sequence=["nonexistent"]),
            _m("b", sequence=["a"]),
            _m("c"),
        ]
        result = resolve_order(modules)
        assert [m.name for m in result] == ["c"]


class TestResolveOrderCycle:
    def test_cycle_detected(self):
        modules = [
            _m("a", sequence=["b"]),
            _m("b", sequence=["a"]),
        ]
        with pytest.raises(CyclicDependencyError):
            resolve_order(modules)

    def test_three_way_cycle(self):
        modules = [
            _m("a", sequence=["c"]),
            _m("b", sequence=["a"]),
            _m("c", sequence=["b"]),
        ]
        with pytest.raises(CyclicDependencyError):
            resolve_order(modules)


class TestValidateDependencies:
    """Enabled modules must not depend on disabled modules."""

    def test_disabled_dep_raises(self):
        enabled = [_m("a", sequence=["b"])]
        all_scanned = [_m("a", sequence=["b"]), _m("b")]
        with pytest.raises(DisabledDependencyError, match="requires 'b'"):
            validate_dependencies(enabled, all_scanned)

    def test_all_enabled_passes(self):
        modules = [_m("a", sequence=["b"]), _m("b")]
        validate_dependencies(modules, modules)  # no exception

    def test_missing_dep_does_not_raise(self):
        """Dep not on disk at all — handled by resolve_order, not here."""
        enabled = [_m("a", sequence=["nonexistent"])]
        all_scanned = [_m("a", sequence=["nonexistent"])]
        validate_dependencies(enabled, all_scanned)  # no exception

    def test_error_message_includes_enable_command(self):
        enabled = [_m("x", sequence=["y"])]
        all_scanned = [_m("x", sequence=["y"]), _m("y")]
        with pytest.raises(DisabledDependencyError, match="agento module:enable y"):
            validate_dependencies(enabled, all_scanned)


class TestGetTransitiveDependents:
    """Find all modules that transitively depend on a given module."""

    def test_direct_dependent(self):
        manifests = [_m("jira"), _m("jira_periodic_tasks", sequence=["jira"])]
        result = get_transitive_dependents("jira", manifests)
        assert result == ["jira_periodic_tasks"]

    def test_transitive_chain(self):
        """A <- B <- C: dependents of A are [B, C]."""
        manifests = [
            _m("a"),
            _m("b", sequence=["a"]),
            _m("c", sequence=["b"]),
        ]
        result = get_transitive_dependents("a", manifests)
        assert result == ["b", "c"]

    def test_no_dependents(self):
        manifests = [_m("a"), _m("b")]
        result = get_transitive_dependents("a", manifests)
        assert result == []

    def test_diamond_dependency_no_duplicates(self):
        """A <- B, A <- C, B <- D, C <- D: dependents of A are [B, C, D]."""
        manifests = [
            _m("a"),
            _m("b", sequence=["a"]),
            _m("c", sequence=["a"]),
            _m("d", sequence=["b", "c"]),
        ]
        result = get_transitive_dependents("a", manifests)
        assert result == ["b", "c", "d"]

    def test_nonexistent_module(self):
        manifests = [_m("a")]
        result = get_transitive_dependents("nonexistent", manifests)
        assert result == []
