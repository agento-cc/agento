from __future__ import annotations

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
    )
