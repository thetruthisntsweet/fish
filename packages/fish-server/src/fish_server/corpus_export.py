"""Corpus membership and export (docs/corpus.md §6, §7; T1.6).

    python -m fish_server.corpus_export --out corpus.jsonl            # research export
    python -m fish_server.corpus_export --out release.jsonl --public  # CC BY 4.0 release

Membership is computed at every export from the latest flags, never decided by hand. A person
is eligible when their latest age event confirms 18+ and their latest consent event allows
research use (and, for ``--public``, the public release). A game enters when it has ended
under the rules (finished, or stopped at 1,000 asks), at least one person played in it, and
every person who held a seat in it is eligible. One ineligible person removes the whole game.
A withdrawal is a new consent row, so the next export simply leaves those games out.

Each game is written as one ``fish-corpus-v1`` record (``fish_rules.corpus``), one per line,
in order of start time. Release game ids are ``g-000001``, ``g-000002``, ... in that order,
and every person appears under a pseudonym drawn at random for this export, the same in all
its games and unrelated to any internal id. Records are built with ``corpus_record``, which
reads each one back, so a game the log cannot reproduce stops the export instead of being
written. Contact data, internal ids and wall-clock times never appear; a game's date is kept
to the month.

The export only reads, so it connects as the server's own login (``FISH_DATABASE_URL``).
"""

import argparse
import json
import secrets
import sys
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from sqlalchemy import Connection, Engine, create_engine, pool, select, text

from fish_rules.codec import ACTION_ENCODING, action_from_data
from fish_rules.corpus import CorpusError, corpus_record
from fish_rules.engine import replay
from fish_rules.state import new_game
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.settings import database_url

COMPLETED: Final = ("finished", "unfinished")

_ELIGIBLE: Final = """
    WITH consent AS (
        SELECT DISTINCT ON (player_id) player_id, research_use, public_release
        FROM consent_events ORDER BY player_id, at DESC, event_id DESC
    ), age AS (
        SELECT DISTINCT ON (player_id) player_id, confirmed_18_plus
        FROM age_events ORDER BY player_id, at DESC, event_id DESC
    )
    SELECT consent.player_id FROM consent JOIN age USING (player_id)
    WHERE consent.research_use AND age.confirmed_18_plus
      AND (consent.public_release OR NOT :public)
"""


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
    ineligible: int = 0
    pseudonyms: dict[uuid.UUID, str] = field(default_factory=dict[uuid.UUID, str])

    def lines(self) -> list[str]:
        return [
            f"games stored: {self.games}",
            f"exported: {self.exported}",
            f"left out, not ended: {self.not_ended}",
            f"left out, abandoned: {self.abandoned}",
            f"left out, no person played: {self.no_person}",
            f"left out, a person not eligible: {self.ineligible}",
            f"people: {len(self.pseudonyms)}",
        ]


def eligible_people(conn: Connection, *, public: bool) -> set[uuid.UUID]:
    """The people eligible now (§6), for the research export or the public release."""
    return set(conn.execute(text(_ELIGIBLE), {"public": public}).scalars())


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
                }
            )
        else:
            seats.append(
                {"person": None, "cohort": None, "agent": seat["agent"], "memory": seat["memory"],
                 "k": seat["k"], "note": None}
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
    }
    try:
        return corpus_record(
            seed, actions, state, game=info, seats=seats, times=times, causes=causes, log=log
        )
    except CorpusError as error:
        raise ExportError(f"game {game_id} is not a valid record: {error}") from None


def export(conn: Connection, *, public: bool) -> tuple[list[dict[str, object]], Summary]:
    """Every corpus game as a record, in order of start time, and the summary (§6, §7)."""
    summary = Summary()
    eligible = eligible_people(conn, public=public)
    people: dict[object, list[object]] = {}
    for game_id, player_id in conn.execute(
        select(db.seats.c.game_id, db.seats.c.player_id).where(db.seats.c.player_id.is_not(None))
    ):
        people.setdefault(game_id, []).append(player_id)
    games = conn.execute(
        select(db.games, db.game_endings.c.completion)
        .outerjoin(db.game_endings, db.games.c.game_id == db.game_endings.c.game_id)
        .order_by(db.games.c.started_at, db.games.c.game_id)
    ).mappings()
    records: list[dict[str, object]] = []
    for game in games:
        summary.games += 1
        held = people.get(game["game_id"], [])
        if game["completion"] is None:
            summary.not_ended += 1
        elif game["completion"] not in COMPLETED:
            summary.abandoned += 1
        elif not held:
            summary.no_person += 1
        elif not all(person in eligible for person in held):
            summary.ineligible += 1
        else:
            release_id = f"g-{len(records) + 1:06d}"
            records.append(_record(conn, dict(game), release_id, summary))
    summary.exported = len(records)
    return records, summary


def write_lines(records: Sequence[dict[str, object]]) -> Iterator[str]:
    """JSON Lines: one compact record per line, keys sorted."""
    for record in records:
        yield json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.corpus_export", description="Export the corpus."
    )
    parser.add_argument("--out", type=Path, required=True, help="a new JSON Lines file")
    parser.add_argument("--public", action="store_true", help="the CC BY 4.0 release")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists; refusing to overwrite it")
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            records, summary = export(conn, public=args.public)
    except ExportError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    with args.out.open("w", encoding="utf-8") as out:
        out.writelines(write_lines(records))
    print("\n".join(summary.lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
