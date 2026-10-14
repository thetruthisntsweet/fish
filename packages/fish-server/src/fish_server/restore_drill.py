"""Backup-restore drill for a Render database (T2.1 subtask 13).

Proves that a point-in-time restore actually brings data back. Run from the Render Shell of
the server (the database accepts no outside connections). Full procedure:
docs/runbooks/restore-drill.md.

    python -m fish_server.restore_drill mark             # write a marker row; note the time
    python -m fish_server.restore_drill damage           # delete it: the "accident"
    python -m fish_server.restore_drill check --url URL  # is the marker in database URL?
    python -m fish_server.restore_drill cleanup          # drop the drill table

Without --url, commands use FISH_ADMIN_DATABASE_URL (the live staging database, as its
owner). The drill table is not part of the schema and never reaches production.
"""

import argparse
import sys

from sqlalchemy import Engine, create_engine, pool, text

from fish_server.settings import admin_database_url, normalize_database_url

TABLE = "restore_drill"
LABEL = "restore-drill-marker"


def _engine(url: str | None) -> Engine:
    return create_engine(
        normalize_database_url(url) if url else admin_database_url(), poolclass=pool.NullPool
    )


def mark(engine: Engine) -> str:
    """Create the drill table if needed, insert the marker, return the database's time."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {TABLE} ("
                " id serial PRIMARY KEY, label text NOT NULL,"
                " created_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        conn.execute(text(f"INSERT INTO {TABLE} (label) VALUES (:label)"), {"label": LABEL})
        return str(conn.execute(text("SELECT now()")).scalar())


def damage(engine: Engine) -> int:
    """Delete every marker row. Returns how many were deleted."""
    with engine.begin() as conn:
        return conn.execute(
            text(f"DELETE FROM {TABLE} WHERE label = :label"), {"label": LABEL}
        ).rowcount


def count_markers(engine: Engine) -> int:
    """How many marker rows the database holds (0 if the drill table does not exist)."""
    with engine.connect() as conn:
        exists = conn.execute(text(f"SELECT to_regclass('{TABLE}') IS NOT NULL")).scalar()
        if not exists:
            return 0
        found = conn.execute(
            text(f"SELECT count(*) FROM {TABLE} WHERE label = :label"), {"label": LABEL}
        ).scalar()
        return int(found or 0)


def cleanup(engine: Engine) -> None:
    """Remove the drill table entirely."""
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fish_server.restore_drill")
    parser.add_argument("command", choices=["mark", "damage", "check", "cleanup"])
    parser.add_argument("--url", help="database URL (default: FISH_ADMIN_DATABASE_URL)")
    args = parser.parse_args(argv)
    engine = _engine(args.url)
    try:
        if args.command == "mark":
            print(f"Marker written at database time {mark(engine)}.")
            print("Wait at least 10 minutes, then run: damage")
        elif args.command == "damage":
            print(
                f"Deleted {damage(engine)} marker row(s). Restore to a time between 'mark' and now."
            )
        elif args.command == "check":
            found = count_markers(engine)
            print("PASS: marker present." if found else "FAIL: marker not found.")
            return 0 if found else 1
        else:
            cleanup(engine)
            print(f"Dropped table {TABLE}.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
