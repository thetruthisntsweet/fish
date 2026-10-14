"""Tests for fish_server.database (T2.1 subtask 13)."""

import pytest

from fish_server.database import dispose_engine, get_engine, schema_revision
from fish_server.settings import DATABASE_URL_VAR


def test_get_engine_is_shared_and_uses_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, "postgresql://u:p@localhost:1/db")
    engine = get_engine()
    assert engine is get_engine()
    assert engine.url.drivername == "postgresql+psycopg"


def test_schema_revision_of_an_unmigrated_database_is_none(
    monkeypatch: pytest.MonkeyPatch, fresh_database_url: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, fresh_database_url)
    assert schema_revision(get_engine()) is None


def test_schema_revision_after_migrating(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, migrated_database_url)
    assert schema_revision(get_engine()) == "0001"


def test_dispose_engine_forgets_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, "postgresql://u:p@localhost:1/db")
    first = get_engine()
    dispose_engine()
    assert get_engine() is not first
    dispose_engine()
    dispose_engine()  # safe to call when there is no engine
