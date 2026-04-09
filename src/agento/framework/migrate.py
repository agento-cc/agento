from __future__ import annotations

import logging
from pathlib import Path

import pymysql

SQL_DIR = Path(__file__).parent / "sql"

_BOOTSTRAP_SQL = """\
CREATE TABLE IF NOT EXISTS schema_migration (
    version     VARCHAR(255) NOT NULL PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# MySQL error codes for idempotent ALTER handling
_IGNORABLE_ERRORS = {
    1050,  # Table already exists (e.g. re-running CREATE after partial failure)
    1054,  # Unknown column (e.g. CHANGE on already-renamed column)
    1060,  # Duplicate column name
    1061,  # Duplicate key name
    1091,  # Can't DROP; check that column/key exists
}


def _ensure_migrations_table(conn: pymysql.Connection) -> None:
    """Create schema_migration table if it doesn't exist.

    Also ensures the ``module`` column exists (added in migration 011).
    The ALTER is idempotent — error 1060 (duplicate column) is silently
    ignored so this is safe to call before migration 011 has been applied.
    """
    with conn.cursor() as cur:
        cur.execute(_BOOTSTRAP_SQL)
        try:
            cur.execute(
                "ALTER TABLE schema_migration "
                "ADD COLUMN module VARCHAR(255) NOT NULL DEFAULT 'framework'"
            )
        except pymysql.err.OperationalError as exc:
            if exc.args[0] not in _IGNORABLE_ERRORS:
                raise
    conn.commit()


def get_applied(
    conn: pymysql.Connection,
    module: str = "framework",
) -> set[str]:
    """Return set of version strings already applied for *module*."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version FROM schema_migration WHERE module = %s",
            (module,),
        )
        return {row["version"] for row in cur.fetchall()}


def get_all_versions(
    sql_dir: Path | None = None,
) -> list[tuple[str, Path]]:
    """Discover all SQL migration files, sorted by filename.

    Returns (version, path) tuples where version is the filename stem.
    *sql_dir* defaults to the framework ``sql/`` directory.
    """
    directory = sql_dir or SQL_DIR
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("*.sql"))
    return [(f.stem, f) for f in files]


def get_pending(
    conn: pymysql.Connection,
    module: str = "framework",
    sql_dir: Path | None = None,
) -> list[tuple[str, Path]]:
    """Return (version, path) pairs not yet applied, sorted by filename."""
    _ensure_migrations_table(conn)
    applied = get_applied(conn, module=module)
    return [(v, p) for v, p in get_all_versions(sql_dir=sql_dir) if v not in applied]


def apply_migration(
    conn: pymysql.Connection,
    version: str,
    path: Path,
    logger: logging.Logger | None = None,
    module: str = "framework",
) -> None:
    """Execute one SQL file and record it in schema_migration.

    Each statement is executed individually. ALTERs that fail with
    ignorable errors (duplicate column, unknown column, etc.) are
    skipped to support idempotent re-runs on existing databases.
    """
    _log = logger or logging.getLogger(__name__)
    raw_text = path.read_text()
    # Strip comment-only lines BEFORE splitting on ";" — comments may
    # contain semicolons (e.g. "-- see 001; already applied") which would
    # incorrectly split statements.
    sql_text = "\n".join(
        line for line in raw_text.splitlines()
        if not line.strip().startswith("--")
    )

    prefix = f"  [{module}/{version}]" if module != "framework" else f"  [{version}]"

    with conn.cursor() as cur:
        for statement in sql_text.split(";"):
            stmt = statement.strip()
            if not stmt:
                continue
            try:
                cur.execute(stmt)
            except pymysql.err.OperationalError as exc:
                if exc.args[0] in _IGNORABLE_ERRORS:
                    _log.info(f"{prefix} Skipped (already applied): {exc.args[1]}")
                    continue
                raise

        cur.execute(
            "INSERT INTO schema_migration (version, module) VALUES (%s, %s)",
            (version, module),
        )
    conn.commit()
    _log.info(f"{prefix} Applied successfully")

    from .event_manager import get_event_manager
    from .events import MigrationAppliedEvent

    get_event_manager().dispatch(
        "migration_apply_after",
        MigrationAppliedEvent(version=version, module=module, path=path),
    )


def migrate(
    conn: pymysql.Connection,
    logger: logging.Logger | None = None,
    module: str = "framework",
    sql_dir: Path | None = None,
) -> list[str]:
    """Apply all pending migrations for *module*. Returns list of applied versions."""
    _log = logger or logging.getLogger(__name__)

    pending = get_pending(conn, module=module, sql_dir=sql_dir)

    if not pending:
        _log.info(f"No pending migrations for {module}.")
        return []

    _log.info(f"Found {len(pending)} pending migration(s) for {module}:")
    applied = []
    for version, path in pending:
        apply_migration(conn, version, path, _log, module=module)
        applied.append(version)

    return applied
