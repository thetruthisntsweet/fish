"""Alembic environment for the Fish database (T2.1 subtask 9).

The URL comes from FISH_DATABASE_URL, unless the caller (for example a test) has already
set ``sqlalchemy.url`` on the Alembic config.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from fish_server.db import metadata
from fish_server.settings import database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url = config.get_main_option("sqlalchemy.url") or database_url()


def run_migrations_offline() -> None:
    """Print the SQL instead of running it: ``alembic upgrade head --sql``."""
    context.configure(
        url=url,
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations, each inside a transaction."""
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
