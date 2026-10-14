"""Everything that runs before a new server version starts (T2.1 subtasks 13 and 14).

Render's pre-deploy command (render.yaml). Any failure exits non-zero, which cancels the
deploy and leaves the running version untouched.

1. Apply migrations as the database owner.
2. Create or update the server's own login (``fish_server``).
3. Log in as ``fish_server`` and confirm it can read but cannot create tables.

    python -m fish_server.deploy                 # from the directory holding alembic.ini
"""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import DBAPIError

from fish_server.privileges import check, sync_login_role
from fish_server.settings import admin_database_url, app_password, database_url


def run(alembic_ini: Path) -> list[str]:
    """Migrate, sync the login, check it. Returns the problems found (empty: all good)."""
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", admin_database_url().replace("%", "%%"))
    command.upgrade(cfg, "head")

    admin = create_engine(admin_database_url(), poolclass=pool.NullPool)
    try:
        print(f"Login role: {sync_login_role(admin, app_password())}.")
    finally:
        admin.dispose()

    app = create_engine(database_url(), poolclass=pool.NullPool)
    try:
        return check(app)
    finally:
        app.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fish_server.deploy")
    parser.add_argument("--alembic-ini", type=Path, default=Path("alembic.ini"))
    args = parser.parse_args(argv)
    try:
        problems = run(args.alembic_ini)
    except DBAPIError as error:
        # One readable line instead of a traceback; the deploy is cancelled either way.
        detail = str(error.orig).strip().replace("\n", " ")
        problems = [f"database refused a step: {detail}"]
        if "CREATEROLE" in detail:
            problems.append("the database owner needs the CREATEROLE attribute (T2.1 §11)")
    for problem in problems:
        print(f"FAIL: {problem}")
    if problems:
        return 1
    print("Pre-deploy checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
