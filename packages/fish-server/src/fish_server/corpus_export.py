"""Corpus membership and export (docs/corpus.md §6, §7; T1.6, T3.2).

    python -m fish_server.corpus_export --out corpus.jsonl
    python -m fish_server.corpus_export --out /tmp/corpus-2026-12-14.jsonl.gz   # gzipped

Membership is computed at every export from stored flags, never decided by hand (Research
Plan §6). A game enters when it has ended under the rules (finished, or stopped at 1,000
asks), at least one person played in it, every person's seat has its consent flags (copied
from that person's acceptance when the game started, ``seat_consents``), and nobody who held a
seat in it has withdrawn. One withdrawal removes every game that person played, whole, with
the other seats' moves. Everyone who plays has agreed to the CC BY 4.0 release, so the one
export is both the research corpus and the release.

Each game is written as one ``fish-corpus-v2`` record (``fish_rules.corpus``), one per line,
in order of start time, with each person's seat consent flags. Release game ids are
``g-000001``, ``g-000002``, ... in that order, and every person appears under a pseudonym
drawn at random for this export, the same in all its games and unrelated to any internal id.
Records are built with ``corpus_record``, which reads each one back, so a game the log
cannot reproduce stops the export instead of being written. Contact data, internal ids and
wall-clock times never appear; a game's date is kept to the month.

The export only reads, so it connects as the server's own login (``FISH_DATABASE_URL``).
It builds and writes one game at a time, so it needs little memory however large the corpus
is: it runs on the server's own instance during the study, beside games in progress. The
file is written under a temporary name and renamed when complete, so a failed export leaves
no file; a name ending ``.gz`` is gzipped. It prints the summary, the file's size and its
SHA-256, to check a copy against (``scripts/check_export.py``).
"""

import argparse
import gzip
import hashlib
import json
import secrets
import sys
import uuid
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Final, Literal, cast

from sqlalchemy import Connection, Engine, create_engine, pool, select, text

from fish_rules.codec import ACTION_ENCODING, action_from_data
from fish_rules.corpus import CorpusError, corpus_record
from fish_rules.engine import replay
from fish_rules.state import new_game
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.settings import database_url

COMPLETED: Final = ("finished", "unfinished")

_UNCONSENTED: Final = """
    SELECT DISTINCT seats.game_id FROM seats
    LEFT JOIN seat_consents USING (game_id, seat)
    WHERE seats.player_id IS NOT NULL AND seat_consents.game_id IS NULL
"""
"""Games with a person's seat that has no consent flags."""

_WITHDRAWN: Final = """
    SELECT DISTINCT seats.game_id FROM seats JOIN withdrawals USING (player_id)
"""
"""Games in which someone who has withdrawn held a seat."""


class ExportError(Exception):
    """A stored game cannot be exported as a valid record."""


@dataclass
class Summary:
    """How many games the export considered, and why each one left out was left out."""

    games: int = 0
    exported: int = 0
    not_ended: int = 0
    abandoned: int = 0
    no_person: int = 0
    unconsented: int = 0
    withdrawn: int = 0
    pseudonyms: dict[uuid.UUID, str] = field(default_factory=dict[uuid.UUID, str])

    def lines(self) -> list[str]:
        return [
            f"games stored: {self.games}",
            f"exported: {self.exported}",
            f"left out, not ended: {self.not_ended}",
            f"left out, abandoned: {self.abandoned}",
            f"left out, no person played: {self.no_person}",
            f"left out, a person's seat without consent: {self.unconsented}",
            f"left out, a person withdrew: {self.withdrawn}",
            f"people: {len(self.pseudonyms)}",
        ]


def _pseudonym(summary: Summary, person: uuid.UUID) -> str:
    """The person's pseudonym in this export: 64 random bits, drawn the first time they appear.
    Two people drawing the same one is too unlikely to plan for, and would stop the export
    (a record cannot seat one person twice) rather than merge them."""
    if person not in summary.pseudonyms:
        summary.pseudonyms[person] = f"p-{secrets.token_hex(8)}"
    return summary.pseudonyms[person]


def _record(
    conn: Connection, game: dict[str, object], release_id: str, summary: Summary
) -> dict[str, object]:
    game_id = game["game_id"]
    if game["ruleset"] != RULESET_VERSION or game["action_encoding"] != ACTION_ENCODING:
        raise ExportError(
            f"game {game_id} was played under ruleset {game['ruleset']!r} and encoding "
            f"{game['action_encoding']!r}; this export reads {RULESET_VERSION!r} and "
            f"{ACTION_ENCODING!r}"
        )
    seed = int(cast(int, game["seed"]))
    rows = conn.execute(
        select(db.actions).where(db.actions.c.game_id == game_id).order_by(db.actions.c.seq)
    ).mappings()
    actions, times, causes = [], [], []
    for row in rows:
        actions.append(action_from_data(row["action"]))
        times.append((row["received_us"], row["sent_us"]))
        causes.append(
            {"seat": row["cause_seat"]}
            if row["cause_seat"] is not None
            else {"timer": row["cause_timer"]}
        )
    try:
        steps = list(replay(seed, actions))
    except ValueError as error:
        raise ExportError(f"game {game_id} does not replay: {error}") from None
    state = steps[-1][0] if steps else new_game(seed)
    notes: dict[int, str] = dict(
        conn.execute(
            select(db.note_answers.c.seat, db.note_answers.c.answer).where(
                db.note_answers.c.game_id == game_id
            )
        ).all()
    )
    c = db.seat_consents.c
    flags: dict[int, dict[str, object]] = {
        row["seat"]: {
            "version": row["version"],
            "us_resident_adult": row["us_resident_adult"],
            "agrees": row["agrees"],
            "no_outside_communication": row["no_outside_communication"],
        }
        for row in conn.execute(select(db.seat_consents).where(c.game_id == game_id)).mappings()
    }
    seats: list[dict[str, object]] = []
    for seat in conn.execute(
        select(db.seats, db.players.c.cohort)
        .outerjoin(db.players, db.seats.c.player_id == db.players.c.player_id)
        .where(db.seats.c.game_id == game_id)
        .order_by(db.seats.c.seat)
    ).mappings():
        if seat["player_id"] is not None:
            seats.append(
                {
                    "person": _pseudonym(summary, seat["player_id"]),
                    "cohort": seat["cohort"],
                    "agent": None,
                    "memory": "human",
                    "k": None,
                    "note": notes.get(seat["seat"], "unanswered"),
                    "consent": flags[seat["seat"]],
                }
            )
        else:
            seats.append(
                {"person": None, "cohort": None, "agent": seat["agent"], "memory": seat["memory"],
                 "k": seat["k"], "note": None, "consent": None}
            )  # fmt: skip
    log = [
        {"type": row["type"], "after": row["after_seq"], "at_us": row["at_us"], "seat": row["seat"]}
        | cast(dict[str, object], row["data"])
        for row in conn.execute(
            select(db.server_log)
            .where(db.server_log.c.game_id == game_id)
            .order_by(db.server_log.c.row_id)
        ).mappings()
    ]
    info = {
        "id": release_id,
        "month": game["started_at"].strftime("%Y-%m"),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        "completion": game["completion"],
        "matchmaking": game["matchmaking"],
        "cohort_table": game["cohort_table"],
        "server_commit": game["server_commit"],
        "protocol_version": game["protocol_version"],
        "bot_delays": game["bot_delays"],
    }
    try:
        return corpus_record(
            seed, actions, state, game=info, seats=seats, times=times, causes=causes, log=log
        )
    except CorpusError as error:
        raise ExportError(f"game {game_id} is not a valid record: {error}") from None


type Standing = Literal[
    "exported", "not_ended", "abandoned", "no_person", "withdrawn", "unconsented"
]
"""Where a stored game stands with the corpus: in it, or why it is left out."""


def membership(conn: Connection) -> dict[uuid.UUID, Standing]:
    """Every stored game's standing with the corpus, now (§6). The export writes the games
    that stand ``exported``; ``fish_server.stats`` counts them."""
    unconsented = set(conn.execute(text(_UNCONSENTED)).scalars())
    withdrawn = set(conn.execute(text(_WITHDRAWN)).scalars())
    people = set(
        conn.execute(
            select(db.seats.c.game_id).where(db.seats.c.player_id.is_not(None)).distinct()
        ).scalars()
    )
    games = conn.execute(
        select(db.games.c.game_id, db.game_endings.c.completion).outerjoin(
            db.game_endings, db.games.c.game_id == db.game_endings.c.game_id
        )
    )
    standing: dict[uuid.UUID, Standing] = {}
    for game_id, completion in games:
        if completion is None:
            standing[game_id] = "not_ended"
        elif completion not in COMPLETED:
            standing[game_id] = "abandoned"
        elif game_id not in people:
            standing[game_id] = "no_person"
        elif game_id in withdrawn:
            standing[game_id] = "withdrawn"
        elif game_id in unconsented:
            standing[game_id] = "unconsented"
        else:
            standing[game_id] = "exported"
    return standing


def records(
    conn: Connection, summary: Summary, only: Collection[uuid.UUID] | None = None
) -> Iterator[dict[str, object]]:
    """Every corpus game as a record, in order of start time, one at a time; ``summary``
    counts them as they go, and is complete once the last is taken (§6, §7). With ``only``,
    just the stored games it names are considered (``fish_server.pilot_report``)."""
    standing = membership(conn)
    query = (
        select(db.games, db.game_endings.c.completion)
        .outerjoin(db.game_endings, db.games.c.game_id == db.game_endings.c.game_id)
        .order_by(db.games.c.started_at, db.games.c.game_id)
    )
    if only is not None:
        query = query.where(db.games.c.game_id.in_(list(only)))
    games = conn.execute(query).mappings()
    for game in games.all():  # one small row a game; each record is read on its own
        summary.games += 1
        where = standing[game["game_id"]]
        if where == "exported":
            release_id = f"g-{summary.exported + 1:06d}"
            record = _record(conn, dict(game), release_id, summary)
            summary.exported += 1
            yield record
        else:
            setattr(summary, where, getattr(summary, where) + 1)


def export(conn: Connection) -> tuple[list[dict[str, object]], Summary]:
    """Every corpus game as a record, all at once, and the summary: for tests and small
    corpora. ``main`` writes them one at a time instead."""
    summary = Summary()
    return list(records(conn, summary)), summary


def write_lines(games: Iterable[dict[str, object]]) -> Iterator[str]:
    """JSON Lines: one compact record per line, keys sorted."""
    for record in games:
        yield json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.corpus_export", description="Export the corpus."
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="a new JSON Lines file (.gz: gzipped)"
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    if out.exists():
        parser.error(f"{out} exists; refusing to overwrite it")
    partial = out.with_name(f"{out.name}.partial")
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    summary = Summary()
    try:
        with engine.connect() as conn, _open(partial) as file:
            for line in write_lines(records(conn, summary)):
                file.write(line)
    except ExportError as error:
        partial.unlink(missing_ok=True)
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()
    partial.rename(out)
    print("\n".join(summary.lines()))
    print(f"file: {out} ({out.stat().st_size:,} bytes)")
    print(f"sha256: {sha256(out)}")
    return 0


def _open(path: Path) -> IO[str]:
    """``path`` for writing text, gzipped if its name (less ``.partial``) ends ``.gz``."""
    if path.name.removesuffix(".partial").endswith(".gz"):
        return gzip.open(path, "wt", encoding="utf-8")
    return path.open("w", encoding="utf-8")


def sha256(path: Path) -> str:
    """The SHA-256 of the file's bytes, as ``shasum -a 256`` prints it."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
