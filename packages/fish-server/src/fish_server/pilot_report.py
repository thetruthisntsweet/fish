"""What the pilot measured (T4.2; docs/runbooks/pilot.md §4). Aggregates only: no game, seat or
person is named, and nothing is written to the database.

    python -m fish_server.pilot_report --since 2026-12-01
    python -m fish_server.pilot_report --since 2026-12-01 --out pilot.json

Run it in ``fish-staging``'s Shell after the last pilot night. It reads the games that started
on or after ``--since`` (Eastern), and takes every time from their corpus records, so it uses
the same games and the same definitions as the study's analyses:

- **game length**: deal to last action, of finished games. Its median, rounded to five minutes,
  is M3's ``{N}`` (docs/recruitment.md §5);
- **share of game time in call windows**: from each Call press to the window's close, over
  the same games' length (Research Plan §2);
- **response times by kind**: a person's turn (an ask or a call), Call press, assignment and
  after-call choice (a choice or a vote), as ``fish_rules.corpus.response_times`` defines them
  (docs/corpus.md §5.3). With ``--out``, all 101 percentiles of each go to a JSON file: the
  bots' delays are drawn from them (R.8.8) and the H1c placebo uses them;
- **round trips**, **handovers**, **disconnections** and **rejected inputs**, and how many
  games were abandoned or are still being played.
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

from sqlalchemy import Connection, Engine, create_engine, pool, text

from fish_rules.corpus import CorpusGame, read_corpus_record, response_times
from fish_rules.events import Ask, Assign, Call, Choose, CloseWindow, Declare, OpenWindow, Vote
from fish_server.corpus_export import Standing, Summary, membership, records
from fish_server.settings import database_url

ZONE: Final = "America/New_York"

KINDS: Final[dict[str, str]] = {
    "turn": "a turn: ask or call",
    "press": "a Call press",
    "assign": "an assignment",
    "choice": "an after-call choice or vote",
}
"""The kinds of decision a response time belongs to, as the bots' delays are drawn by kind."""

KIND_OF: Final[dict[type, str]] = {
    Ask: "turn",
    Call: "turn",
    Declare: "press",
    Assign: "assign",
    Choose: "choice",
    Vote: "choice",
}

SHOWN: Final = (10, 25, 50, 75, 90)
"""The percentiles the printed report shows; ``--out`` has all 101."""

_SINCE: Final = f"""
    SELECT game_id FROM games
    WHERE CAST(:since AS date) IS NULL
       OR (started_at AT TIME ZONE '{ZONE}')::date >= CAST(:since AS date)
"""


@dataclass
class Pilot:
    """Everything the report says, summed over the games it read."""

    since: date | None
    standing: Counter[Standing] = field(default_factory=Counter[Standing])
    """The games that started since then, by where they stand with the corpus."""
    lengths_us: list[int] = field(default_factory=list[int])
    """Each finished corpus game's length."""
    window_us: int = 0
    """Time with a call window open, in the same games."""
    windows: int = 0
    responses_us: dict[str, list[int]] = field(
        default_factory=lambda: {kind: list[int]() for kind in KINDS}
    )
    round_trips_us: list[int] = field(default_factory=list[int])
    handovers: Counter[str] = field(default_factory=Counter[str])
    """By reason: ``turn_timeout`` or ``disconnect``."""
    games_handed_over: int = 0
    disconnections: int = 0
    rejected: Counter[str] = field(default_factory=Counter[str])
    """By reason: ``illegal``, ``stale`` or ``malformed``."""

    @property
    def games(self) -> int:
        """Corpus games read: every time but the lengths comes from these."""
        return self.standing["exported"]

    def add(self, game: CorpusGame) -> None:
        """Add one corpus game's times and log."""
        for step, value in zip(game.steps, response_times(game), strict=True):
            if value is not None:
                self.responses_us[KIND_OF[type(step.action)]].append(value)
        if game.game.completion == "finished" and game.steps:
            self.lengths_us.append(game.steps[-1].sent_us)
            opened: int | None = None
            for step in game.steps:
                if isinstance(step.action, OpenWindow):
                    opened = step.received_us
                    self.windows += 1
                elif isinstance(step.action, CloseWindow) and opened is not None:
                    self.window_us += step.received_us - opened
                    opened = None
        handed = False
        for row in game.log:
            match row.type:
                case "rtt":
                    self.round_trips_us.append(int(row.fields["rtt_us"]))  # pyright: ignore[reportArgumentType]
                case "handover":
                    self.handovers[str(row.fields["reason"])] += 1
                    handed = True
                case "connection" if row.fields["state"] == "disconnected":
                    self.disconnections += 1
                case "rejected":
                    self.rejected[str(row.fields["reason"])] += 1
                case _:
                    pass
        self.games_handed_over += handed


def read(conn: Connection, since: date | None) -> Pilot:
    """The pilot's figures, from the games that started on or after ``since`` (Eastern)."""
    chosen = set(conn.execute(text(_SINCE), {"since": since}).scalars())
    standing = membership(conn)
    pilot = Pilot(since, Counter(standing[g] for g in chosen))
    for record in records(conn, Summary(), only=chosen):
        pilot.add(read_corpus_record(record))
    return pilot


# ---------------------------------------------------------------- figures


def percentiles(values: Sequence[int]) -> list[int]:
    """The 0th to 100th percentiles of ``values`` (linear between order statistics), or an
    empty list if there are none."""
    if not values:
        return []
    if len(values) == 1:
        return [values[0]] * 101
    cuts = statistics.quantiles(values, n=100, method="inclusive")
    return [min(values), *(round(c) for c in cuts), max(values)]


def five_minutes(minutes: float) -> int:
    """Rounded to the nearest five minutes, halves up, as M3's ``{N}`` is."""
    return int(minutes / 5 + 0.5) * 5


def figures(pilot: Pilot) -> dict[str, object]:
    """The report as data: what ``--out`` writes, and what the printed report shows."""
    lengths = sorted(pilot.lengths_us)
    total = sum(lengths)
    return {
        "since": pilot.since.isoformat() if pilot.since else None,
        "games": {
            "started": sum(pilot.standing.values()),
            **{where: pilot.standing[where] for where in sorted(pilot.standing)},
            "finished": len(lengths),
            "handed_over": pilot.games_handed_over,
        },
        "game_length_us": percentiles(lengths),
        "window_share": pilot.window_us / total if total else None,
        "windows": pilot.windows,
        "response_times_us": {
            kind: {"count": len(values), "percentiles": percentiles(values)}
            for kind, values in pilot.responses_us.items()
        },
        "round_trip_us": percentiles(pilot.round_trips_us),
        "round_trips": len(pilot.round_trips_us),
        "handovers": dict(sorted(pilot.handovers.items())),
        "disconnections": pilot.disconnections,
        "rejected": dict(sorted(pilot.rejected.items())),
    }


def _s(us: float) -> str:
    return f"{us / 1e6:.1f}"


def _row(label: str, value: object, note: str = "") -> str:
    return f"  {label:<30}{value!s:>7}" + (f"  {note}" if note else "")


def _counts(counter: dict[str, int]) -> str:
    return ", ".join(f"{what} {n}" for what, n in counter.items()) or "none"


def report(pilot: Pilot) -> list[str]:
    data = figures(pilot)
    counts = pilot.standing
    since = (
        f"started from {pilot.since:%a} {pilot.since.day} {pilot.since:%b %Y}"
        if pilot.since
        else "all games"
    )
    lines = [
        f"Fish pilot report: {since} (Eastern)",
        "",
        "Games",
        _row("started", sum(counts.values())),
        _row("in the corpus", counts["exported"], "(every figure below is from these)"),
        _row("abandoned", counts["abandoned"]),
        _row("still being played", counts["not_ended"]),
    ]
    other = {
        "no person played": counts["no_person"],
        "a seat without consent": counts["unconsented"],
        "a person withdrew": counts["withdrawn"],
    }
    if any(other.values()):
        lines.append(
            _row(
                "ended, left out otherwise",
                sum(other.values()),
                f"({_counts({k: v for k, v in other.items() if v})})",
            )
        )
    lines.append(_row("with a bot handover", pilot.games_handed_over))

    lengths = sorted(pilot.lengths_us)
    lines += ["", "Game length (finished games, deal to last action)"]
    if lengths:
        cut = percentiles(lengths)
        median = statistics.median(lengths) / 60e6
        lines += [
            _row("finished games", len(lengths)),
            _row(
                "median, minutes",
                f"{median:.1f}",
                f"(middle half {cut[25] / 60e6:.1f} to {cut[75] / 60e6:.1f})",
            ),
            _row("M3's {N}, minutes", five_minutes(median), "(the median, to the nearest five)"),
            _row("call windows opened", pilot.windows),
            _row("share of time in windows", f"{100 * data['window_share']:.1f}%"),  # pyright: ignore[reportOperatorIssue]
        ]
    else:
        lines.append("  no finished games")

    lines += [
        "",
        "Response times, seconds (a person's input, from when they could act)",
        f"  {'kind':<30}{'count':>7}" + "".join(f"{f'{p}%':>7}" for p in SHOWN),
    ]
    for kind, label in KINDS.items():
        values = pilot.responses_us[kind]
        cut = percentiles(values)
        shown = "".join(f"{_s(cut[p]):>7}" for p in SHOWN) if cut else ""
        lines.append(f"  {label:<30}{len(values):>7}{shown}")
    negative = sum(v < 0 for values in pilot.responses_us.values() for v in values)
    if negative:
        lines.append(f"  ({negative} below zero: sent while the update they answer was going out)")

    trips = percentiles(pilot.round_trips_us)
    lines += ["", "Connections"]
    if trips:
        lines.append(
            _row(
                "round trip, median ms",
                round(trips[50] / 1000),
                f"(95th percentile {round(trips[95] / 1000)} ms;"
                f" {len(pilot.round_trips_us)} measured)",
            )
        )
    lines += [
        _row("disconnections", pilot.disconnections),
        _row(
            "handovers to a bot",
            sum(pilot.handovers.values()),
            f"({_counts(dict(sorted(pilot.handovers.items())))})",
        ),
        _row(
            "inputs rejected",
            sum(pilot.rejected.values()),
            f"({_counts(dict(sorted(pilot.rejected.items())))})",
        ),
    ]
    return lines


def write(path: Path, data: dict[str, object]) -> None:
    """``data`` as JSON at ``path``, which must not exist yet."""
    with path.open("x") as out:
        json.dump(data, out, indent=1, sort_keys=True)
        out.write("\n")


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date like 2026-12-01") from None


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.pilot_report",
        description="What the pilot measured: aggregates only.",
    )
    parser.add_argument(
        "--since", type=_date, help="only games started on or after this day, Eastern (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--out", type=Path, help="also write the figures, with every percentile, as JSON here"
    )
    args = parser.parse_args(argv)
    if args.out is not None and args.out.exists():
        parser.error(f"{args.out} exists already: choose another name")
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            pilot = read(conn, args.since)
    finally:
        engine.dispose()
    print("\n".join(report(pilot)))
    if args.out is not None:
        write(args.out, figures(pilot))
        print(f"\nWrote {args.out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
