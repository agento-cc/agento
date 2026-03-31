from __future__ import annotations

import sys

import pymysql
from pymysql.cursors import DictCursor


def get_connection(config: object) -> pymysql.Connection:
    """Create a single MySQL connection. Caller must close it."""
    return pymysql.connect(
        host=config.mysql_host,
        port=config.mysql_port,
        user=config.mysql_user,
        password=config.mysql_password,
        database=config.mysql_database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
        init_command="SET time_zone = '+00:00'",
    )


def get_connection_or_exit(config: object) -> pymysql.Connection:
    """Like get_connection(), but prints a friendly error and exits on failure."""
    try:
        return get_connection(config)
    except pymysql.err.OperationalError:
        host = getattr(config, "mysql_host", "?")
        port = getattr(config, "mysql_port", "?")
        print(
            f"Error: Cannot connect to MySQL at {host}:{port}\n"
            "\n"
            "If running locally (outside Docker), set connection params:\n"
            "  export MYSQL_HOST=127.0.0.1\n"
            "  export MYSQL_PASSWORD=cronagent_pass\n"
            "\n"
            "Or add them to docker/.env or secrets.env.\n"
            "\n"
            "If running in Docker:\n"
            "  docker compose exec cron agento <command>",
            file=sys.stderr,
        )
        sys.exit(1)
