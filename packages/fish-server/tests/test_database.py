"""Tests for fish_server.database (T2.1 subtasks 13 and 14)."""

import pytest
from sqlalchemy import create_engine, pool

from fish_server.database import dispose_engine, get_engine, schema_revision
from fish_server.settings import ADMIN_DATABASE_URL_VAR, APP_PASSWORD_VAR, app_login_role


@pytest.fixture
def placeholder_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADMIN_DATABASE_URL_VAR, "postgresql://owner:pw@localhost:1/db")
    monkeypatch.setenv(APP_PASSWORD_VAR, "app-pw-0123456789abcdef")


@pytest.mark.usefixtures("placeholder_env")
def test_get_engine_is_shared_and_logs_in_as_the_app() -> None:
    engine = get_engine()
    assert engine is get_engine()
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.username == app_login_role()


@pytest.mark.usefixtures("placeholder_env")
def test_dispose_engine_forgets_the_engine() -> None:
    first = get_engine()
    dispose_engine()
    assert get_engine() is not first
    dispose_engine()
    dispose_engine()  # safe to call when there is no engine


def test_schema_revision_of_an_unmigrated_database_is_none(fresh_database_url: str) -> None:
    engine = create_engine(fresh_database_url, poolclass=pool.NullPool)
    assert schema_revision(engine) is None
    engine.dispose()


@pytest.mark.usefixtures("server_env")
def test_the_app_login_can_read_the_schema_revision(head_revision: str) -> None:
    assert schema_revision(get_engine()) == head_revision
