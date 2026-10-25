"""Tests for the Alembic migrations (T2.1 subtask 9).

The offline tests always run. The database test uses the ``fresh_database_url`` fixture
from conftest.py, so it is skipped without FISH_TEST_DATABASE_URL.
"""

import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, pool, text

REPO = Path(__file__).resolve().parents[3]


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


def test_offline_sql_creates_the_version_table_and_the_corpus_tables() -> None:
    out = io.StringIO()
    command.upgrade(alembic_config("postgresql+psycopg://x@localhost/x", out), "head", sql=True)
    sql = out.getvalue()
    assert "CREATE TABLE alembic_version" in sql
    assert "INSERT INTO alembic_version (version_num) VALUES ('0001')" in sql
    assert "CREATE SEQUENCE signup_numbers" in sql
    for table in ("players", "games", "seats", "actions", "server_log"):
        assert f"CREATE TABLE {table} (" in sql
    assert "CREATE TRIGGER actions_no_update_delete" in sql


def current_versions(url: str) -> list[str]:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        if not inspect(engine).has_table("alembic_version"):
            return []
        with engine.connect() as conn:
            return list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trip(fresh_database_url: str) -> None:
    cfg = alembic_config(fresh_database_url)
    head = ScriptDirectory.from_config(cfg).get_current_head()

    command.upgrade(cfg, "head")
    assert current_versions(fresh_database_url) == [head]

    command.downgrade(cfg, "base")
    assert current_versions(fresh_database_url) == []

    command.upgrade(cfg, "head")
    assert current_versions(fresh_database_url) == [head]
