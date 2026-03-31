"""setup:upgrade orchestrator — Magento's ``bin/magento setup:upgrade`` equivalent.

Runs the full setup sequence in order:
1. Framework SQL migrations
2. Module SQL migrations (dependency order)
3. Data patches (topological order by ``require()``)
4. Cron installation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymysql

from .bootstrap import CORE_MODULES_DIR, USER_MODULES_DIR
from .crontab import (
    assemble,
    build_managed_block,
    collect_cron_jobs,
    extract_unmanaged,
    get_current_crontab,
    install_crontab,
)
from .data_patch import apply_patch, get_all_pending, resolve_patch_order
from .dependency_resolver import resolve_order, validate_dependencies
from .event_manager import get_event_manager
from .events import CrontabInstalledEvent, SetupBeforeEvent, SetupCompleteEvent
from .migrate import get_pending, migrate
from .module_loader import scan_modules
from .module_status import filter_enabled

FRAMEWORK_SQL_DIR = Path(__file__).parent / "sql"
FRAMEWORK_CRON_JSON = Path(__file__).parent / "cron.json"


@dataclass
class SetupResult:
    """Summary of what ``setup:upgrade`` applied (or would apply in dry-run)."""

    framework_migrations: list[str] = field(default_factory=list)
    module_migrations: dict[str, list[str]] = field(default_factory=dict)
    data_patches: dict[str, list[str]] = field(default_factory=dict)
    cron_changed: bool = False

    @property
    def has_work(self) -> bool:
        return bool(
            self.framework_migrations
            or self.module_migrations
            or self.data_patches
            or self.cron_changed
        )


def setup_upgrade(
    conn: pymysql.Connection,
    logger: logging.Logger,
    *,
    dry_run: bool = False,
    core_dir: str = CORE_MODULES_DIR,
    user_dir: str = USER_MODULES_DIR,
) -> SetupResult:
    """Run the full setup:upgrade sequence."""
    em = get_event_manager()
    result = SetupResult()

    em.dispatch("agento_setup_before", SetupBeforeEvent(dry_run=dry_run))

    # 1. Framework SQL migrations
    if dry_run:
        fw_pending = get_pending(conn, module="framework")
        result.framework_migrations = [v for v, _ in fw_pending]
    else:
        result.framework_migrations = migrate(conn, logger, module="framework")

    # 2. Module SQL migrations in dependency order
    all_scanned = scan_modules(core_dir) + scan_modules(user_dir)
    enabled = filter_enabled(all_scanned)
    validate_dependencies(enabled, all_scanned)
    manifests = resolve_order(enabled)

    for m in manifests:
        sql_dir = m.path / "sql"
        if not sql_dir.is_dir():
            continue
        if dry_run:
            pending = get_pending(conn, module=m.name, sql_dir=sql_dir)
            if pending:
                result.module_migrations[m.name] = [v for v, _ in pending]
        else:
            applied = migrate(conn, logger, module=m.name, sql_dir=sql_dir)
            if applied:
                result.module_migrations[m.name] = applied

    # 3. Data patches (topological order by require())
    pending_patches = get_all_pending(manifests, conn)
    if pending_patches:
        ordered = resolve_patch_order(pending_patches)
        if dry_run:
            for m, p in ordered:
                result.data_patches.setdefault(m.name, []).append(p["name"])
        else:
            for m, p in ordered:
                apply_patch(m, p, conn, logger)
                result.data_patches.setdefault(m.name, []).append(p["name"])

    # 4. Cron installation
    jobs = collect_cron_jobs(manifests, FRAMEWORK_CRON_JSON)
    current = get_current_crontab()
    unmanaged = extract_unmanaged(current)
    managed = build_managed_block(jobs)
    new_crontab = assemble(unmanaged, managed)
    result.cron_changed = install_crontab(new_crontab, dry_run=dry_run)
    if result.cron_changed and not dry_run:
        em.dispatch(
            "agento_crontab_installed",
            CrontabInstalledEvent(job_count=len(jobs)),
        )

    em.dispatch(
        "agento_setup_complete",
        SetupCompleteEvent(result=result, dry_run=dry_run),
    )

    return result
