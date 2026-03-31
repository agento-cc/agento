from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _module_dirs() -> tuple[Path, Path]:
    """Resolve core and user module directories (Docker vs local dev)."""
    project_root = Path(__file__).resolve().parents[4]
    core_dir = project_root / "src" / "agento" / "modules"
    user_dir = Path("/app/code") if Path("/app/code").is_dir() else project_root / "app" / "code"
    return core_dir, user_dir


def cmd_make_module(args: argparse.Namespace) -> None:
    from ..module_scaffold import scaffold_module

    if args.base_dir:
        base_dir = Path(args.base_dir)
    else:
        # Default: app/code/ relative to project root
        # In Docker: /app/code/, locally: find from package location
        docker_path = Path("/app/code")
        base_dir = docker_path if docker_path.is_dir() else Path(__file__).resolve().parents[4] / "app" / "code"

    module_dir = scaffold_module(
        name=args.name,
        base_dir=base_dir,
        description=args.description,
        tools=args.tool,
    )
    print(f"Module '{args.name}' created at {module_dir}")


def _set_module_state(name: str, enabled: bool) -> None:
    """Enable or disable a module by name. Exits if module not found."""
    from ..module_loader import scan_modules
    from ..module_status import set_enabled

    core_dir, user_dir = _module_dirs()
    all_names = {m.name for m in scan_modules(str(core_dir)) + scan_modules(str(user_dir))}
    if name not in all_names:
        print(f"Module '{name}' not found")
        sys.exit(1)

    set_enabled(name, enabled)
    state = "enabled" if enabled else "disabled"
    print(f"Module '{name}' {state}")


def cmd_module_enable(args: argparse.Namespace) -> None:
    _set_module_state(args.name, True)


def cmd_module_disable(args: argparse.Namespace) -> None:
    _set_module_state(args.name, False)


def cmd_module_list(args: argparse.Namespace) -> None:
    from ..dependency_resolver import resolve_order
    from ..module_loader import scan_modules
    from ..module_status import is_enabled, read_module_status

    core_dir, user_dir = _module_dirs()
    all_modules = resolve_order(scan_modules(str(core_dir)) + scan_modules(str(user_dir)))
    status = read_module_status()

    for m in all_modules:
        enabled = is_enabled(m.name, status)
        mark = "\u2714" if enabled else "\u2718"
        state = "enabled" if enabled else "disabled"
        seq = f" (requires: {', '.join(m.sequence)})" if m.sequence else ""
        print(f"  {mark} {m.name:20s} {state:10s} {m.version:8s} {m.description}{seq}")


def cmd_module_validate(args: argparse.Namespace) -> None:
    from ..module_validator import validate_all, validate_module

    core_dir, user_dir = _module_dirs()

    if args.name:
        # Validate specific module
        module_dir = None
        for search_dir in (core_dir, user_dir):
            candidate = search_dir / args.name
            if candidate.is_dir():
                module_dir = candidate
                break
        if module_dir is None:
            print(f"Module '{args.name}' not found")
            sys.exit(1)

        errors = validate_module(module_dir)
        if errors:
            print(f"\u2718 {args.name}")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            print(f"\u2714 {args.name}")
    else:
        # Validate all
        results = validate_all(core_dir, user_dir)
        all_modules = set()
        for scan_dir in (core_dir, user_dir):
            if scan_dir.is_dir():
                for entry in sorted(scan_dir.iterdir()):
                    if entry.is_dir() and not entry.name.startswith("_") and not entry.name.startswith("."):
                        all_modules.add(entry.name)

        has_errors = False
        for name in sorted(all_modules):
            if name in results:
                print(f"\u2718 {name}")
                for err in results[name]:
                    print(f"  - {err}")
                has_errors = True
            else:
                print(f"\u2714 {name}")

        if has_errors:
            sys.exit(1)
