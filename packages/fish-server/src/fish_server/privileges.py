"""Database roles: what the running server may and may not do (T2.1 subtask 14, §11).

* ``fish_app`` (no login): the privileges. Reads and inserts on every table the migrations
  create, never UPDATE, DELETE or TRUNCATE, never creating tables. Granted by migration
  0002 as *default privileges*, so each future table gets exactly this automatically.
* ``fish_server`` (login): the identity the server connects as. A member of ``fish_app``
  and nothing else. Its password comes from FISH_APP_DB_PASSWORD; ``sync`` sets it.

Tables that must never change once written (the event log, T3.2) are additionally made
append-only with a trigger (``append_only_sql``), which stops UPDATE, DELETE and TRUNCATE
even for the database owner.

    python -m fish_server.privileges sync    # create or update fish_server (admin URL)
    python -m fish_server.privileges check   # prove fish_server can read but not alter
"""

import argparse
import re
import sys

from sqlalchemy import Connection, Engine, create_engine, pool, text
from sqlalchemy.exc import DBAPIError

from fish_server.settings import (
    APP_LOGIN_ROLE,
    admin_database_url,
    app_password,
    database_url,
)

APP_GROUP_ROLE = "fish_app"

# Passwords are written into a CREATE/ALTER ROLE statement, which cannot take bind
# parameters, so only characters that are safe inside an SQL string are allowed. Render's
# generated values (base64) and any long random string fit.
_PASSWORD_PATTERN = re.compile(r"[A-Za-z0-9+/=_\-.]{16,200}")


def validate_password(password: str) -> str:
    """Return ``password`` if it is 16-200 characters of letters, digits and ``+/=_-.``."""
    if not _PASSWORD_PATTERN.fullmatch(password):
        raise ValueError(
            "FISH_APP_DB_PASSWORD must be 16-200 characters of letters, digits and +/=_-."
        )
    return password


def sync_login_role(engine: Engine, password: str) -> str:
    """Create the ``fish_server`` login, or update its password, and make it a member of
    ``fish_app``. Safe to run on every deploy. Returns "created" or "updated"."""
    password = validate_password(password)
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": APP_LOGIN_ROLE}
        ).scalar()
        if exists:
            # Only the password: restating attributes such as NOSUPERUSER needs superuser
            # rights, which the database owner on Render does not have.
            conn.execute(text(f"ALTER ROLE {APP_LOGIN_ROLE} WITH LOGIN PASSWORD '{password}'"))
        else:
            conn.execute(
                text(
                    f"CREATE ROLE {APP_LOGIN_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB "
                    f"NOCREATEROLE PASSWORD '{password}'"
                )
            )
        conn.execute(text(f"GRANT {APP_GROUP_ROLE} TO {APP_LOGIN_ROLE}"))
    return "updated" if exists else "created"


def _denied(conn: Connection, statement: str) -> bool:
    """Run ``statement`` in a savepoint; True if PostgreSQL refused it for lack of rights."""
    savepoint = conn.begin_nested()
    try:
        conn.execute(text(statement))
    except DBAPIError as error:
        savepoint.rollback()
        return getattr(error.orig, "sqlstate", None) == "42501"  # insufficient_privilege
    savepoint.rollback()
    return False


def check(app_engine: Engine) -> list[str]:
    """Connect as the server's login and return every way its rights differ from §11.

    An empty list means: it can log in and read, and it cannot create tables, create roles
    or act as a superuser. Nothing is changed: every probe is rolled back.
    """
    problems: list[str] = []
    with app_engine.connect() as conn:
        who = conn.execute(
            text(
                "SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, "
                " pg_has_role(current_user, :group, 'MEMBER')"
                " FROM pg_roles WHERE rolname = current_user"
            ),
            {"group": APP_GROUP_ROLE},
        ).one()
        if who[0] != APP_LOGIN_ROLE:
            problems.append(f"connected as {who[0]!r}, expected {APP_LOGIN_ROLE!r}")
        if who[1] or who[2] or who[3]:
            problems.append("has superuser, create-role or create-database rights")
        if not who[4]:
            problems.append(f"is not a member of {APP_GROUP_ROLE}")
        try:
            conn.execute(text("SELECT version_num FROM alembic_version")).all()
        except DBAPIError:
            problems.append("cannot read alembic_version")
            conn.rollback()
        if not _denied(conn, "CREATE TABLE fish_privilege_probe (x int)"):
            problems.append("can create tables")
        conn.rollback()
    return problems


def append_only_sql(table: str) -> list[str]:
    """Statements that make ``table`` append-only, for use in a migration (T3.2).

    Triggers reject UPDATE, DELETE and TRUNCATE for every role, the owner included, so a
    mistake in an admin script cannot alter recorded games either. The trigger function
    ``fish_forbid_change`` is created by migration 0002.
    """
    return [
        f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION fish_forbid_change()",
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION fish_forbid_change()",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fish_server.privileges")
    parser.add_argument("command", choices=["sync", "check"])
    args = parser.parse_args(argv)
    if args.command == "sync":
        admin = create_engine(admin_database_url(), poolclass=pool.NullPool)
        try:
            print(f"{APP_LOGIN_ROLE}: {sync_login_role(admin, app_password())}.")
        finally:
            admin.dispose()
        return 0
    app = create_engine(database_url(), poolclass=pool.NullPool)
    try:
        problems = check(app)
    finally:
        app.dispose()
    for problem in problems:
        print(f"FAIL: {APP_LOGIN_ROLE} {problem}")
    if not problems:
        print(f"PASS: {APP_LOGIN_ROLE} can read, and cannot create tables or roles.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
