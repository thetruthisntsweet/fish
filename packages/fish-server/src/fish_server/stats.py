"""How the study is going (T4.1, T4.4): sign-ups, the corpus against its target of 1,000 games,
each week's pace, bot handovers, and how long games take. Counts only, never an address.

    python -m fish_server.stats

Run it in the service's **Shell** every Monday, before that week's M4 (docs/recruitment.md
§3): if two full weeks in a row fall short of 110 corpus games, it says to add a Friday night.
On the pilot site it leaves out the target and the pace, and its game length gives M3's
``{N}``. A game counts for the corpus exactly as the export decides
(``fish_server.corpus_export.membership``), so a withdrawal lowers past weeks too. Weeks run
Monday to Sunday, Eastern time, as the game nights do.
"""

import argparse
import statistics
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from sqlalchemy import Connection, Engine, create_engine, pool, text

from fish_server.corpus_export import Standing, membership
from fish_server.settings import consent_version, database_url

TARGET: Final = 1_000
WEEKLY: Final = 110
"""Corpus games a week that reach the target by the last day (docs/recruitment.md §3)."""
FIRST_FULL_WEEK: Final = date(2026, 12, 14)
LAST_DAY: Final = date(2027, 2, 14)
ZONE: Final = "America/New_York"
DAYS_SHOWN: Final = 14

LEFT_OUT: Final[dict[Standing, str]] = {
    "abandoned": "abandoned",
    "withdrawn": "a person withdrew",
    "unconsented": "a seat without consent",
    "no_person": "no person played",
}

_GAMES: Final = f"""
    SELECT g.game_id, (g.started_at AT TIME ZONE '{ZONE}')::date AS day, g.cohort_table,
           EXISTS (SELECT 1 FROM server_log l WHERE l.game_id = g.game_id AND l.type = 'handover')
           OR (SELECT count(*) FROM seats s WHERE s.game_id = g.game_id
               AND s.player_id IS NOT NULL) < 6 AS bot,
           e.completion = 'finished' AS finished,
           (SELECT max(a.sent_us) FROM actions a WHERE a.game_id = g.game_id) AS length_us
    FROM games g LEFT JOIN game_endings e USING (game_id)
"""

_PEOPLE: Final = """
    SELECT count(*) AS signed_up,
           count(*) FILTER (WHERE NOT p.cohort) AS group_1,
           count(*) FILTER (WHERE p.cohort) AS group_2,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM consents c
                             WHERE c.player_id = p.player_id AND c.version = :current))
               AS accepted,
           count(*) FILTER (WHERE EXISTS (SELECT 1 FROM withdrawals w
                             WHERE w.player_id = p.player_id)) AS withdrawn
    FROM players p
"""


@dataclass(frozen=True, slots=True)
class Game:
    id: uuid.UUID
    day: date
    """The day it started, Eastern."""
    standing: Standing
    cohort_table: bool
    bot: bool
    """A bot held a seat at some point: from the start, or after a handover."""
    minutes: float | None
    """How long a finished game took, start to last action."""

    @property
    def week(self) -> date:
        return self.day - timedelta(days=self.day.weekday())


@dataclass(frozen=True, slots=True)
class People:
    signed_up: int
    group_1: int
    group_2: int
    accepted: int
    withdrawn: int


def read(conn: Connection, current: str) -> tuple[People, list[Game], date]:
    """Everyone, every game, and today's date, Eastern."""
    standing = membership(conn)
    games = [
        Game(
            row.game_id,
            row.day,
            standing[row.game_id],
            row.cohort_table,
            row.bot,
            row.length_us / 60_000_000 if row.finished and row.length_us is not None else None,
        )
        for row in conn.execute(text(_GAMES))
    ]
    counted = conn.execute(text(_PEOPLE), {"current": current}).one()
    people = People(*counted)
    today = conn.execute(text(f"SELECT (now() AT TIME ZONE '{ZONE}')::date")).scalar_one()
    return people, sorted(games, key=lambda g: (g.day, str(g.id))), today


def _day(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def _row(label: str, value: int) -> str:
    return f"  {label:<24}{value:>6}"


def _share(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "-"


def report(people: People, games: list[Game], today: date, current: str) -> list[str]:
    pilot = current.endswith("-pilot")
    corpus = [g for g in games if g.standing == "exported"]
    lines = [
        f"Fish study on {_day(today)} {today.year} (Eastern), study information {current}",
        "",
        "People",
        _row("signed up", people.signed_up)
        + f"  (group 1: {people.group_1}, group 2: {people.group_2})",
        _row(f"accepted {current}", people.accepted),
        _row("withdrawn", people.withdrawn),
        "",
        "Games",
        _row("in the corpus", len(corpus)) + ("" if pilot else f" of {TARGET:,}"),
        _row("playing now", sum(g.standing == "not_ended" for g in games)),
    ]
    out = {reason: sum(g.standing == reason for g in games) for reason in LEFT_OUT}
    why = ", ".join(f"{label} {out[reason]}" for reason, label in LEFT_OUT.items() if out[reason])
    lines.append(_row("ended, left out", sum(out.values())) + (f"  ({why})" if why else ""))
    bots = sum(g.bot for g in corpus)
    lines.append(_row("a bot held a seat", bots) + f"  ({_share(bots, len(corpus))} of corpus)")
    lengths = sorted(g.minutes for g in games if g.minutes is not None)
    if lengths:
        quarters = statistics.quantiles(lengths, n=4) if len(lengths) > 1 else lengths * 3
        lines.append(
            _row("minutes a game takes", round(statistics.median(lengths)))
            + f"  (middle half {quarters[0]:.0f} to {quarters[2]:.0f};"
            f" {len(lengths)} finished games)"
        )

    weeks = sorted({g.week for g in games})
    if weeks:
        lines += ["", f"  {'Week (Mon - Sun)':<24}corpus  started  group 2 tables  bot held a seat"]
        for week in weeks:
            mine = [g for g in games if g.week == week]
            kept = [g for g in mine if g.standing == "exported"]
            label = f"{_day(week)} - {_day(week + timedelta(days=6))}"
            note = "  (so far)" if week + timedelta(days=6) >= today else ""
            lines.append(
                f"  {label:<24}{len(kept):>6}{len(mine):>9}{sum(g.cohort_table for g in mine):>16}"
                f"{sum(g.bot for g in kept):>17}{note}"
            )

    if not pilot:
        full = [w for w in weeks if w >= FIRST_FULL_WEEK and w + timedelta(days=6) < today]
        by_week = {w: sum(g.week == w and g.standing == "exported" for g in games) for w in full}
        lines += ["", f"Pace: {WEEKLY} corpus games a week reach {TARGET:,} by {_day(LAST_DAY)}."]
        if full:
            last = full[-1]
            short = by_week[last] < WEEKLY
            lines.append(
                f"  last full week ({_day(last)}): {by_week[last]}" + ("  short" if short else "")
            )
            recent = [by_week[w] for w in full[-2:]]
            weeks_left = max(0, (LAST_DAY - today).days + 1) / 7
            ahead = len(corpus) + statistics.mean(recent) * weeks_left
            rate = "last week's rate" if len(recent) == 1 else "last two weeks' rate"
            lines.append(f"  at the {rate}: about {ahead:,.0f} by the last day")
            if len(recent) == 2 and all(n < WEEKLY for n in recent):
                lines.append(
                    "  Two full weeks in a row short: add a Friday night (docs/recruitment.md §3)."
                )
        else:
            lines.append("  no full week yet")

    recent_days = [today - timedelta(days=d) for d in range(DAYS_SHOWN - 1, -1, -1)]
    played = [d for d in recent_days if any(g.day == d for g in games)]
    if played:
        lines += ["", f"  {f'Day (last {DAYS_SHOWN} days)':<24}corpus  started"]
        for day in played:
            mine = [g for g in games if g.day == day]
            kept = sum(g.standing == "exported" for g in mine)
            lines.append(f"  {_day(day):<24}{kept:>6}{len(mine):>9}")
    return lines


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.stats", description="How the study is going."
    )
    parser.parse_args(argv)
    current = consent_version()
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            people, games, today = read(conn, current)
    finally:
        engine.dispose()
    print("\n".join(report(people, games, today, current)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
