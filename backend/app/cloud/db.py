"""Postgres access is server-only; public clients never receive these credentials."""
from contextlib import contextmanager

from app.cloud.settings import value


@contextmanager
def connect():
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(value("SUPABASE_DB_URL"), row_factory=dict_row, connect_timeout=10) as db:
        yield db
