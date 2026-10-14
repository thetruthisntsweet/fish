"""Tests for fish_server.privileges and migration 0002 (T2.1 subtask 14).

These prove §11 against a real PostgreSQL: the server's login can read and insert, and is
refused everything else; append-only tables refuse changes even from the owner.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, pool, text
from sqlalchemy.exc import DBAPIError

from fish_server.privileges import (
    APP_GROUP_ROLE,
    append_only_sql,
    check,
    main,
    sync_login_role,
    validate_password,
)
from fish_server.settings import APP_LOGIN_ROLE, database_url

INSUFFICIENT_PRIVILEGE = "42501"


@pytest.fixture
def owner(server_env: str) -> Iterator[Engine]:
    """The database owner, with a sample table created the way migrations create tables."""
    engine = create_engine(server_env, poolclass=pool.NullPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sample (id serial PRIMARY KEY, note text)"))
        conn.execute(text("INSERT INTO sample (note) VALUES ('written by the owner')"))
    yield engine
    engine.dispose()


@pytest.fixture
def app(owner: Engine) -> Iterator[Engine]:
    """The fish_server login, exactly as the running server connects."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def refused(engine: Engine, statement: str) -> bool:
    """True if PostgreSQL refuses ``statement`` for lack of privilege."""
    try:
        with engine.begin() as conn:
            conn.execute(text(statement))
    except DBAPIError as error:
        return getattr(error.orig, "sqlstate", None) == INSUFFICIENT_PRIVILEGE
    return False


def test_app_login_can_read_and_insert(app: Engine) -> None:
    with app.begin() as conn:
        conn.execute(text("INSERT INTO sample (note) VALUES ('written by the server')"))
        notes = conn.execute(text("SELECT note FROM sample ORDER BY id")).scalars().all()
    assert notes == ["written by the owner", "written by the server"]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE sample SET note = 'changed'",
        "DELETE FROM sample",
        "TRUNCATE sample",
        "CREATE TABLE intruder (x int)",
        "DROP TABLE sample",
        "CREATE ROLE intruder",
        "ALTER ROLE fish_server CREATEROLE",
    ],
)
def test_app_login_is_refused_everything_else(app: Engine, statement: str) -> None:
    assert refused(app, statement), statement


@pytest.mark.parametrize(
    "statement",
    ["UPDATE sample SET note = 'changed'", "DELETE FROM sample", "TRUNCATE sample"],
)
def test_append_only_tables_refuse_changes_even_from_the_owner(
    owner: Engine, statement: str
) -> None:
    with owner.begin() as conn:
        for sql in append_only_sql("sample"):
            conn.execute(text(sql))
    assert refused(owner, statement), statement
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO sample (note) VALUES ('appending still works')"))
        assert conn.execute(text("SELECT count(*) FROM sample")).scalar() == 2


def test_check_passes_for_the_app_login(app: Engine) -> None:
    assert check(app) == []


def test_check_flags_a_login_with_too_many_rights(owner: Engine) -> None:
    problems = check(owner)  # the owner: wrong user, superuser in tests, can create tables
    assert any("expected 'fish_server'" in p for p in problems)
    assert "has superuser, create-role or create-database rights" in problems
    assert "can create tables" in problems


def test_check_flags_a_login_that_cannot_read(owner: Engine, app: Engine) -> None:
    with owner.begin() as conn:
        conn.execute(text(f"REVOKE SELECT ON alembic_version FROM {APP_GROUP_ROLE}"))
    assert check(app) == ["cannot read alembic_version"]


def test_sync_creates_then_updates_and_old_password_stops_working(server_env: str) -> None:
    owner = create_engine(server_env, poolclass=pool.NullPool)
    with owner.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {APP_LOGIN_ROLE}"))
    assert sync_login_role(owner, "first-password-0123456789") == "created"
    assert sync_login_role(owner, "second-password-0123456789") == "updated"
    owner.dispose()
    old = create_engine(
        database_url().replace("test-app-password-0123456789", "first-password-0123456789"),
        poolclass=pool.NullPool,
    )
    with pytest.raises(DBAPIError, match="password authentication failed"), old.connect():
        pass
    old.dispose()


@pytest.mark.parametrize(
    "password",
    ["short", "has space 0123456789", "quote'0123456789abcdef", "x" * 201, ""],
)
def test_unsafe_or_weak_passwords_are_rejected(password: str) -> None:
    with pytest.raises(ValueError, match="16-200 characters"):
        validate_password(password)


def test_render_generated_style_passwords_are_accepted() -> None:
    password = "Zm9vYmFyYmF6cXV4K2dlbmVyYXRlZC8xMjM0NTY3OA=="
    assert validate_password(password) == password


@pytest.mark.usefixtures("server_env")
def test_command_line_sync_and_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sync"]) == 0
    assert f"{APP_LOGIN_ROLE}: updated." in capsys.readouterr().out
    assert main(["check"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_command_line_check_reports_failures(
    server_env: str, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = create_engine(server_env, poolclass=pool.NullPool)
    with owner.begin() as conn:
        conn.execute(text(f"REVOKE SELECT ON alembic_version FROM {APP_GROUP_ROLE}"))
    owner.dispose()
    assert main(["check"]) == 1
    assert "FAIL: fish_server cannot read alembic_version" in capsys.readouterr().out
