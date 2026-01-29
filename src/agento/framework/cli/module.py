from __future__ import annotations

import argparse
import sys


def cmd_make_module(args: argparse.Namespace) -> None:
    from pathlib import Path

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


def cmd_module_validate(args: argparse.Namespace) -> None:
    from pathlib import Path

    from ..module_validator import validate_all, validate_module

    project_root = Path(__file__).resolve().parents[4]
    core_dir = project_root / "src" / "agento" / "modules"
    user_dir = Path("/app/code") if Path("/app/code").is_dir() else project_root / "app" / "code"

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
