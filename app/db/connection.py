"""Database connectivity only; the new document schema is not implemented yet."""

import psycopg

from core.config import PG_DSN


def check_database() -> None:
    with psycopg.connect(PG_DSN, connect_timeout=5) as connection:
        connection.execute("SELECT 1")
