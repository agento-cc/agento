"""agento doctor — check system prerequisites."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from ._output import log_error


def _check_binary(name: str, version_args: list[str] | None = None) -> tuple[bool, str]:
    """Check if a binary is available and get its version."""
    path = shutil.which(name)
    if not path:
        return False, "not found"
    if version_args is None:
        version_args = [name, "--version"]
    try:
        result = subprocess.run(
            version_args,
            capture_output=True, text=True, timeout=10,
        )
        # Extract version from first line of output
        output = (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr) else ""
        return True, output
    except (subprocess.TimeoutExpired, OSError):
        return True, "installed (version unknown)"


def _check_docker_compose() -> tuple[bool, str]:
    """Check Docker Compose V2."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "not found"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, "not found"


def _check_python() -> tuple[bool, str]:
    """Check Python version."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 11)
    return ok, f"Python {version}" + ("" if ok else " (requires >=3.11)")


class DoctorCommand:
    @property
    def name(self) -> str:
        return "doctor"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Check system prerequisites"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace) -> None:
        print("\nAgento Doctor\n")

        checks = []

        # Python
        ok, info = _check_python()
        checks.append(("Python", ok, info))

        # uv
        ok, info = _check_binary("uv")
        checks.append(("uv", ok, info))

        # Docker
        ok, info = _check_binary("docker")
        checks.append(("Docker", ok, info))

        # Docker Compose
        ok, info = _check_docker_compose()
        checks.append(("Docker Compose", ok, info))

        # Node.js
        ok, info = _check_binary("node")
        checks.append(("Node.js", ok, info))

        # npm
        ok, info = _check_binary("npm")
        checks.append(("npm", ok, info))

        # Display results
        for name, ok, info in checks:
            status = "OK" if ok else "MISSING"
            print(f"  {name:20} {status:8} {info}")

        print()

        # Determine available modes
        has_docker = any(name == "Docker" and ok for name, ok, _ in checks)
        has_compose = any(name == "Docker Compose" and ok for name, ok, _ in checks)

        if has_docker and has_compose:
            print("  Docker Compose          ready")
        else:
            print("  Docker Compose          not available (install Docker + Compose)")

        print()

        # Exit code: 0 if Python >= 3.11
        python_ok = any(name == "Python" and ok for name, ok, _ in checks)
        if not python_ok:
            log_error("Python >= 3.11 is required.")
            sys.exit(1)
