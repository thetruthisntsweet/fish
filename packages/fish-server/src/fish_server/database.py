"""The server's connection to its database (T2.1 subtask 13).

One engine (a pool of connections) per process, created on first use so that importing the
server never needs a database: tests and ``/health`` work without one.
"""

from functools import cache

from sqlalchemy import Engine, create_engine, text

from fish_server.settings import database_url


@cache
def get_engine() -> Engine:
    """The process-wide engine for FISH_DATABASE_URL.

    ``pool_pre_ping`` checks each pooled connection before use, so a connection the database
    closed (for example during a Render maintenance window) is replaced instead of failing
    the request.
    """
    return create_engine(database_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)


def dispose_engine() -> None:
    """Close every pooled connection and forget the engine. Called when the server shuts
    down, so connections are closed cleanly instead of being dropped mid-conversation."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()


def schema_revision(engine: Engine) -> str | None:
    """The Alembic revision the database is at, or None if it has never been migrated."""
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('alembic_version') IS NOT NULL")).scalar()
        if not exists:
            return None
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
