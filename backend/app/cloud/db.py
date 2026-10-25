"""Postgres access is server-only; public clients never receive these credentials."""
from contextlib import contextmanager
from threading import Lock

from app.cloud.settings import PROVIDER, value

_pool = None
_pool_lock = Lock()


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connect():
    import psycopg
    from psycopg.rows import dict_row

    if PROVIDER == "aws":
        global _pool
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    import os
                    from psycopg_pool import ConnectionPool
                    from app.cloud.aws_clients import database_dsn
                    _pool = ConnectionPool(database_dsn(), min_size=1,
                                           max_size=int(os.getenv("SENTINEL_DB_POOL_SIZE", "3")),
                                           kwargs={"row_factory": dict_row}, timeout=5,
                                           check=ConnectionPool.check_connection, open=True)
        with _pool.connection() as connection:
            yield connection
    else:
        with psycopg.connect(value("SUPABASE_DB_URL"), row_factory=dict_row, connect_timeout=10) as connection:
            yield connection
