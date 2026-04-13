"""Workspace directory layout constants.

Defines the three-layer workspace structure:
- theme:     template/scaffolding (base for every build)
- build:     compiled readonly workspace per agent_view
- artifacts: writable per-job directory (agent outputs + toolbox I/O)
"""
from __future__ import annotations

import os

BASE_WORKSPACE_DIR = os.environ.get("AGENTO_WORKSPACE_DIR", "/workspace")

THEME_DIR = os.path.join(BASE_WORKSPACE_DIR, "theme")
BUILD_DIR = os.path.join(BASE_WORKSPACE_DIR, "build")
ARTIFACTS_DIR = os.path.join(BASE_WORKSPACE_DIR, "artifacts")
