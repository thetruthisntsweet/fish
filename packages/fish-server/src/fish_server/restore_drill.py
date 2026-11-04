"""Backup-restore drill for a Render database (T2.1 subtask 13, T3.6).

Proves that a point-in-time restore actually brings data back: the marker, every row the
study had when it was written, and a corpus export that still reads. Run from the Render
Shell of the server (the database accepts no outside connections). Full procedure:
docs/runbooks/restore-drill.md.

    python -m fish_server.restore_drill mark             # write a marker row; note the time
    python -m fish_server.restore_drill damage           # delete it: the "accident"
    python -m fish_server.restore_drill check --url URL  # is everything in database URL?
    python -m fish_server.restore_drill cleanup          # drop the drill table

``mark`` records, with the marker, how many rows each append-only table held
(``db.APPEND_ONLY``: those rows are never changed or removed) and how many games the corpus
export held. ``check`` passes when the database at URL has the marker, at least as many rows
in each of those tables, and an export that builds every record (read back and replayed)
with at least as many games. Only a withdrawal after the marker can lower that last number.

Without --url, commands use FISH_ADMIN_DATABASE_URL (the live staging database, as its
owner). The drill table is not part of the schema and never reaches production.
"""

import argparse
import json
import sys

from sqlalchemy import Engine, create_engine, func, pool, select, text

from fish_server import db
from fish_server.corpus_export import ExportError, Summary, records
from fish_server.settings import admin_database_url, normalize_database_url

TABLE = "restore_drill"
LABEL = "restore-drill-marker"
EXPORTED = "corpus export"
"""The key under which ``mark`` records how many games the export held."""


def _engine(url: str | None) -> Engine:
    return create_engine(
        normalize_database_url(url) if url else admin_database_url(), poolclass=pool.NullPool
    )


def held(engine: Engine) -> dict[str, int]:
    """How many rows each append-only table holds, and how many games the corpus export
    holds (every record built, read back and replayed). Raises ExportError if one does not."""
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for name in db.APPEND_ONLY:
            table = db.metadata.tables[name]
            counts[name] = int(conn.execute(select(func.count()).select_from(table)).scalar_one())
        summary = Summary()
        for _ in records(conn, summary):  # one at a time: the drill runs beside live games
            pass
    counts[EXPORTED] = summary.exported
    return counts


def mark(engine: Engine) -> tuple[str, dict[str, int]]:
    """Create the drill table if needed, insert the marker with what the database holds now;
    return the database's time and those counts."""
    counts = held(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {TABLE} ("
                " id serial PRIMARY KEY, label text NOT NULL,"
                " created_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS counts jsonb"))
        conn.execute(
            text(f"INSERT INTO {TABLE} (label, counts) VALUES (:label, CAST(:counts AS jsonb))"),
            {"label": LABEL, "counts": json.dumps(counts)},
        )
        return str(conn.execute(text("SELECT now()")).scalar()), counts


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


def marked(engine: Engine) -> dict[str, int] | None:
    """What the database held when the latest marker was written, or None if no marker
    records it (none at all, or one written before markers carried counts)."""
    if not count_markers(engine):
        return None
    with engine.connect() as conn:
        has = conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                f" WHERE table_name = '{TABLE}' AND column_name = 'counts')"
            )
        ).scalar()
        if not has:
            return None
        found = conn.execute(
            text(f"SELECT counts FROM {TABLE} WHERE label = :label ORDER BY id DESC LIMIT 1"),
            {"label": LABEL},
        ).scalar()
    return None if found is None else {str(k): int(v) for k, v in dict(found).items()}


def check(engine: Engine) -> tuple[list[str], dict[str, int]]:
    """What is missing from the database, compared with the marker (empty if nothing), and
    what it holds."""
    if not count_markers(engine):
        return ["marker not found."], {}
    before = marked(engine)
    if before is None:
        return ["the marker records no counts: write a new one with this version (mark)."], {}
    try:
        now = held(engine)
    except ExportError as error:
        return [f"the corpus export does not build: {error}"], {}
    problems: list[str] = []
    for name, count in before.items():
        if now.get(name, 0) < count:
            why = " (a withdrawal since the marker would explain it)" if name == EXPORTED else ""
            problems.append(f"{name}: {now.get(name, 0)}, fewer than the {count} at mark{why}.")
    return problems, now


def _show(counts: dict[str, int]) -> str:
    return ", ".join(f"{name} {count:,}" for name, count in counts.items())


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
            at, counts = mark(engine)
            print(f"Marker written at database time {at}.")
            print(f"Holding: {_show(counts)}.")
            print("Wait at least 10 minutes, then run: damage")
        elif args.command == "damage":
            print(
                f"Deleted {damage(engine)} marker row(s). Restore to a time between 'mark' and now."
            )
        elif args.command == "check":
            problems, counts = check(engine)
            if counts:
                print(f"Holding: {_show(counts)}.")
            if problems:
                print("\n".join(f"FAIL: {problem}" for problem in problems))
                return 1
            print("PASS: marker present, every row there at mark, and the corpus exports.")
        else:
            cleanup(engine)
            print(f"Dropped table {TABLE}.")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
