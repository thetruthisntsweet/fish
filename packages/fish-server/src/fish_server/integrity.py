"""Whether what the study has stored is whole and consistent (T4.4; docs/corpus.md §3 to §6,
docs/runbooks/collection.md). It only reads.

    python -m fish_server.integrity

Run it in the service's **Shell** every Monday. It checks every stored game, in the corpus or
not, and prints each check with ``ok`` or how many faults it found, then each fault with its
game's ID, so the game can be found. Nothing else is named. Exits 0 if every check is ok and 1
otherwise. A fault is reported and never repaired here: what to do about one is decided and
recorded (docs/runbooks/collection.md §4). A game excluded by such a decision
(``fish_server.exclude``) is counted, and its faults are counted as known without failing.

The checks, by name:

- ``seats``: every game has its six seats.
- ``actions``: a completed game's actions are numbered 0 up with no gap, and it has some.
- ``stale``: no game without an ending has been quiet for an hour. The server ends such games
  ``abandoned`` within minutes (``games.abandon_quiet``), so one left means that stopped.
- ``consent``: every person's seat carries the consent flags copied when its game began.
- ``cohort``: a table from solo matchmaking holds only one group's players and says which; a
  room is never marked as a cohort table (docs/corpus.md §2.1).
- ``draw``: every player is in the group the cohort seed gives their sign-up number.
- ``versions``: every game names encodings and a bot delay table this code knows, and no game
  started since the study opened was played under another ruleset.
- ``seeds``: no two games share a seed.
- ``notes``: every note-taking answer belongs to a person's seat.
- ``two tables``: nobody held a seat in two games at once.
- ``records``: every completed game of this ruleset builds into a corpus record that reads and
  replays to the end the game recorded, withdrawn games included (the export checks only the
  games it writes, and stops at the first that fails).
"""

import argparse
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from sqlalchemy import Connection, Engine, create_engine, pool, text

from fish_agents.delays import versions
from fish_rules.codec import ACTION_ENCODING
from fish_rules.cohort import in_cohort
from fish_rules.state import STATE_ENCODING
from fish_rules.version import RULESET_VERSION
from fish_server.corpus_export import ExportError, Summary, _record  # pyright: ignore[reportPrivateUsage]
from fish_server.settings import cohort_seed, database_url
from fish_server.study import LAUNCH

ZONE: Final = "America/New_York"
SHOWN: Final = 50
"""Faults listed in full; any more are only counted."""


@dataclass(frozen=True, slots=True)
class Fault:
    check: str
    game: uuid.UUID | None
    """The game it is in, or None for a fault of a player's row."""
    detail: str


@dataclass
class Report:
    games: int = 0
    replayed: int = 0
    other_ruleset: int = 0
    """Games under another ruleset, which are left out of the corpus (R.10.2)."""
    excluded: int = 0
    """Games left out by a recorded decision (``fish_server.exclude``)."""
    checks: list[str] = field(default_factory=list[str])
    faults: list[Fault] = field(default_factory=list[Fault])
    known: list[Fault] = field(default_factory=list[Fault])
    """Faults in excluded games: already decided, so they are listed but do not fail."""

    def count(self, check: str) -> int:
        return sum(f.check == check for f in self.faults)


# ---------------------------------------------------------------- the checks

_LAST_WRITE: Final = """
    (g.started_at + make_interval(secs => GREATEST(
        COALESCE((SELECT max(a.sent_us) FROM actions a WHERE a.game_id = g.game_id), 0),
        COALESCE((SELECT max(l.at_us) FROM server_log l WHERE l.game_id = g.game_id), 0)
    ) / 1e6))
"""

_SQL: Final[dict[str, tuple[str, str]]] = {
    "seats": (
        """SELECT g.game_id, count(s.seat) AS n FROM games g LEFT JOIN seats s USING (game_id)
           GROUP BY g.game_id HAVING count(s.seat) <> 6""",
        "{n} seats, not 6",
    ),
    "actions": (
        """SELECT e.game_id, count(a.seq) AS n, max(a.seq) AS top
           FROM game_endings e LEFT JOIN actions a USING (game_id)
           WHERE e.completion <> 'abandoned' GROUP BY e.game_id, e.completion
           HAVING count(a.seq) = 0 OR max(a.seq) <> count(a.seq) - 1""",
        "completed with {n} actions, the last numbered {top}",
    ),
    "stale": (
        f"""SELECT g.game_id, to_char({_LAST_WRITE} AT TIME ZONE '{ZONE}', 'YYYY-MM-DD HH24:MI')
                   AS last
            FROM games g
            WHERE NOT EXISTS (SELECT 1 FROM game_endings e WHERE e.game_id = g.game_id)
              AND {_LAST_WRITE} < now() - interval '1 hour'""",
        "no ending, and nothing written since {last} Eastern",
    ),
    "consent": (
        """SELECT s.game_id, s.seat FROM seats s
           WHERE s.player_id IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM seat_consents c WHERE c.game_id = s.game_id AND c.seat = s.seat)""",
        "seat {seat} is a person's, without consent flags",
    ),
    "cohort": (
        """SELECT g.game_id, g.matchmaking, g.cohort_table,
                  count(*) FILTER (WHERE p.cohort) AS held_out, count(*) AS people
           FROM games g JOIN seats s USING (game_id) JOIN players p USING (player_id)
           GROUP BY g.game_id, g.matchmaking, g.cohort_table
           HAVING (g.matchmaking = 'group' AND g.cohort_table)
               OR (g.matchmaking = 'solo' AND count(*) FILTER (WHERE p.cohort) <>
                   CASE WHEN g.cohort_table THEN count(*) ELSE 0 END)""",
        "{matchmaking}, cohort table {cohort_table}, with {held_out} of {people} people from"
        " the held-out cohort",
    ),
    "seeds": (
        """SELECT g.game_id, g.seed FROM games g
           WHERE EXISTS (SELECT 1 FROM games o WHERE o.seed = g.seed AND o.game_id <> g.game_id)""",
        "shares its seed with another game",
    ),
    "notes": (
        """SELECT n.game_id, n.seat FROM note_answers n JOIN seats s USING (game_id, seat)
           WHERE s.player_id IS NULL""",
        "a note-taking answer for seat {seat}, a bot's",
    ),
    "two tables": (
        # A person holds a seat from the start to their handover, or to the game's last action.
        """WITH held AS (
               SELECT s.game_id, s.player_id, g.started_at AS began,
                      g.started_at + make_interval(secs => COALESCE(
                          (SELECT min(l.at_us) FROM server_log l WHERE l.game_id = s.game_id
                             AND l.seat = s.seat AND l.type = 'handover'),
                          (SELECT max(a.sent_us) FROM actions a WHERE a.game_id = s.game_id),
                          0) / 1e6) AS ended
               FROM seats s JOIN games g USING (game_id) WHERE s.player_id IS NOT NULL)
           SELECT a.game_id, b.game_id AS other FROM held a JOIN held b
             ON a.player_id = b.player_id AND a.game_id <> b.game_id
            AND a.began <= b.began AND b.began < a.ended - interval '5 seconds'""",
        "a person in it was still seated when game {other} began with them",
    ),
}
"""Each check that is one query: what finds its faults, and how a fault reads."""


def _versions(conn: Connection, report: Report) -> None:
    known = set(versions())
    rows = conn.execute(
        text(
            f"""SELECT game_id, ruleset, action_encoding, state_encoding, bot_delays,
                       (started_at AT TIME ZONE '{ZONE}')::date AS day FROM games"""
        )
    )
    for row in rows:
        problems: list[str] = []
        if row.action_encoding != ACTION_ENCODING or row.state_encoding != STATE_ENCODING:
            problems.append(f"encodings {row.action_encoding}, {row.state_encoding}")
        if row.bot_delays not in known:
            problems.append(f"unknown bot delay table {row.bot_delays}")
        if row.ruleset != RULESET_VERSION:
            report.other_ruleset += 1
            if row.day >= LAUNCH:
                problems.append(f"ruleset {row.ruleset} since the study opened")
        report.faults += [Fault("versions", row.game_id, p) for p in problems]


def _draw(conn: Connection, report: Report, seed: int) -> None:
    for row in conn.execute(text("SELECT signup_number, cohort FROM players")):
        if row.cohort != in_cohort(seed, row.signup_number):
            group = "the held-out cohort" if row.cohort else "the main group"
            report.faults.append(
                Fault(
                    "draw",
                    None,
                    f"sign-up number {row.signup_number} is in {group}, against the seed",
                )
            )


def _records(conn: Connection, report: Report) -> None:
    """Build every completed game of this ruleset as the export would, and note any that
    does not read and replay."""
    faulty = {f.game for f in report.faults if f.check in ("seats", "consent", "actions")}
    games = conn.execute(
        text(
            """SELECT g.*, e.completion FROM games g JOIN game_endings e USING (game_id)
               WHERE e.completion <> 'abandoned' AND g.ruleset = :ruleset
               ORDER BY g.started_at, g.game_id"""
        ),
        {"ruleset": RULESET_VERSION},
    ).mappings()
    for game in games.all():
        if game["game_id"] in faulty:  # already reported, and it cannot build
            continue
        try:
            _record(conn, dict(game), "g-000001", Summary())
            report.replayed += 1
        except ExportError as problem:
            detail = str(problem).removeprefix(f"game {game['game_id']} ")
            report.faults.append(Fault("records", game["game_id"], detail))


def check(conn: Connection, seed: int | None) -> Report:
    """Run every check. ``seed`` is the cohort seed, or None to leave ``draw`` out."""
    report = Report(games=conn.execute(text("SELECT count(*) FROM games")).scalar_one())
    for name, (query, words) in _SQL.items():
        report.checks.append(name)
        for row in conn.execute(text(query)).mappings():
            report.faults.append(Fault(name, row["game_id"], words.format(**row)))
    steps: list[tuple[str, Callable[[], None]]] = [
        ("versions", lambda: _versions(conn, report)),
        ("records", lambda: _records(conn, report)),
    ]
    if seed is not None:
        steps.insert(0, ("draw", lambda: _draw(conn, report, seed)))
    for name, step in steps:
        report.checks.append(name)
        step()
    excluded = set(conn.execute(text("SELECT game_id FROM game_exclusions")).scalars())
    report.excluded = len(excluded)
    report.known = [f for f in report.faults if f.game in excluded]
    report.faults = [f for f in report.faults if f.game not in excluded]
    return report


# ---------------------------------------------------------------- the report


def lines(report: Report, today: date) -> list[str]:
    out = [
        f"Fish integrity check on {today:%a} {today.day} {today:%b %Y} (Eastern)",
        "",
        f"  {'games stored':<30}{report.games:>6}",
        f"  {'completed, read and replayed':<30}{report.replayed:>6}",
    ]
    if report.other_ruleset:
        out.append(f"  {'under another ruleset':<30}{report.other_ruleset:>6}  (not in the corpus)")
    if report.excluded:
        out.append(
            f"  {'excluded after a fault':<30}{report.excluded:>6}"
            f"  ({len(report.known)} known faults in them)"
        )
    out += ["", "Checks"]
    for name in report.checks:
        found = report.count(name)
        out.append(f"  {name:<30}{'ok' if not found else f'FAULTS: {found}':>6}")
    if report.faults:
        out += ["", "Faults"]
        for fault in report.faults[:SHOWN]:
            where = f"game {fault.game}" if fault.game is not None else "a player"
            out.append(f"  {fault.check}: {where}: {fault.detail}")
        if len(report.faults) > SHOWN:
            out.append(f"  and {len(report.faults) - SHOWN} more")
        out += ["", f"FAIL: {len(report.faults)} faults (docs/runbooks/collection.md §4)"]
    else:
        out += ["", "PASS"]
    return out


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.integrity",
        description="Check that what the study has stored is whole and consistent.",
    )
    parser.parse_args(argv)
    seed = cohort_seed()
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            report = check(conn, seed)
            today = conn.execute(text(f"SELECT (now() AT TIME ZONE '{ZONE}')::date")).scalar_one()
    finally:
        engine.dispose()
    print("\n".join(lines(report, today)))
    return 1 if report.faults else 0


if __name__ == "__main__":
    sys.exit(main())
