"""Tests for the Alembic migrations (T2.1 subtask 9).

The offline tests always run. The database tests need FISH_TEST_DATABASE_URL (see
.env.example): each creates a throwaway database, migrates it, and drops it afterwards,
so your development data is never touched.
"""

import io
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, make_url, pool, text

REPO = Path(__file__).resolve().parents[3]
ADMIN_URL = os.environ.get("FISH_TEST_DATABASE_URL", "").strip()

needs_database = pytest.mark.skipif(
    not ADMIN_URL,
    reason="FISH_TEST_DATABASE_URL not set: start infra/docker-compose.yml and create .env",
)


def alembic_config(url: str, output: io.StringIO | None = None) -> Config:
    """The repository's alembic.ini, pointed at ``url`` instead of FISH_DATABASE_URL."""
    cfg = Config(str(REPO / "alembic.ini"), output_buffer=output)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # % is special in .ini
    return cfg


def test_history_is_a_single_line_starting_at_the_baseline() -> None:
    script = ScriptDirectory.from_config(alembic_config("postgresql+psycopg://x@localhost/x"))
    assert len(script.get_heads()) == 1, "two migrations claim to be the latest: merge them"
    revisions = list(script.walk_revisions())
    assert revisions[-1].revision == "0001"
    assert revisions[-1].down_revision is None


def test_offline_sql_creates_only_the_version_table() -> None:
    out = io.StringIO()
    command.upgrade(alembic_config("postgresql+psycopg://x@localhost/x", out), "head", sql=True)
    sql = out.getvalue()
    assert "CREATE TABLE alembic_version" in sql
    assert "INSERT INTO alembic_version (version_num) VALUES ('0001')" in sql


@pytest.fixture
def fresh_database_url() -> Iterator[str]:
    """Create an empty database for one test; drop it afterwards, even if the test fails."""
    name = f"fish_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def current_versions(url: str) -> list[str]:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        if not inspect(engine).has_table("alembic_version"):
            return []
        with engine.connect() as conn:
            return list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        engine.dispose()


@needs_database
def test_upgrade_downgrade_upgrade_round_trip(fresh_database_url: str) -> None:
    cfg = alembic_config(fresh_database_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()

    command.upgrade(cfg, "head")
    assert current_versions(fresh_database_url) == [head]

    command.downgrade(cfg, "base")
    assert current_versions(fresh_database_url) == []

    command.upgrade(cfg, "head")
    assert current_versions(fresh_database_url) == [head]
