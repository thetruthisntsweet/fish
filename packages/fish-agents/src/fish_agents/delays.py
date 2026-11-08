"""How long a website bot waits before it acts or presses Call (R.8.8; T4.2), by delay table.

A table has a version, which is recorded with every game (``bot_delays``, docs/corpus.md §3),
and gives each wait in whole microseconds from one generator:

- ``uniform-1.5-4s-v1``, the wait before pilot data existed: uniform from 1.5 to 4 seconds,
  ``1_500_000 + below(2_500_001)``, whatever the decision. The pilot site keeps it.
- a **percentile table**: for each kind of decision (``KINDS``), the 0th to 100th percentiles
  of people's response times, measured in the pilot (``fish_server.pilot_report``). A wait is
  drawn by its inverse distribution function, linear between neighbouring percentiles:
  ``x = below(100_000_000)`` picks percentile ``x / 1,000,000``, and the wait is
  ``p[i] + (p[i+1] - p[i]) * f // 1,000,000`` for ``i, f = divmod(x, 1_000_000)``. All in
  integers, so a game's waits follow from its seed on any machine.

Percentile tables are JSON files in ``fish_agents/delay_tables/``, named by version, and are
never changed once a game has used them: a new pilot or a fix is a new version. The same
tables give the H1c placebo's games human timing (Research Questions §2).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Final

from fish_rules.rng import SplitMix64
from fish_rules.state import Phase

UNIFORM: Final = "uniform-1.5-4s-v1"
UNIFORM_MIN_US: Final = 1_500_000
UNIFORM_MAX_US: Final = 4_000_000

KINDS: Final[dict[str, str]] = {
    "turn": "a turn: ask or call",
    "press": "a Call press",
    "assign": "an assignment",
    "choice": "an after-call choice or vote",
}
"""The kinds of decision a wait is drawn for, and their labels in the pilot report. A turn's
call is grouped with its asks: it is the same decision, and run-out's naming of the next set
(R.6.2) is the same kind of decision as a turn's call."""

KIND_OF_PHASE: Final[dict[Phase, str]] = {
    Phase.TURN: "turn",
    Phase.RUNOUT: "turn",
    Phase.WINDOW: "press",
    Phase.ASSIGN: "assign",
    Phase.CHOOSE: "choice",
    Phase.VOTE: "choice",
}
"""The kind of a decision a seat faces in each phase it can act in."""

POINTS: Final = 101
"""Percentiles in a table: the 0th to the 100th."""
MIN_TIMES: Final = 50
"""The fewest response times of a kind a table is built from: fewer make its tails guesses."""
_TABLES: Final = "delay_tables"


@dataclass(frozen=True, slots=True)
class DelayTable:
    """A version of the bots' waits. ``percentiles`` is None for ``UNIFORM``."""

    version: str
    percentiles: Mapping[str, tuple[int, ...]] | None = None
    stand_in: bool = False
    """Numbers made up before the pilot: never for the study."""

    def draw(self, rng: SplitMix64, kind: str) -> int:
        """One wait for a decision of ``kind``, in microseconds."""
        if kind not in KINDS:
            raise ValueError(f"no kind of decision {kind!r}; the kinds are {', '.join(KINDS)}")
        if self.percentiles is None:
            return UNIFORM_MIN_US + rng.below(UNIFORM_MAX_US - UNIFORM_MIN_US + 1)
        points = self.percentiles[kind]
        i, f = divmod(rng.below(100_000_000), 1_000_000)
        return points[i] + (points[i + 1] - points[i]) * f // 1_000_000


def check(data: Mapping[str, object]) -> DelayTable:
    """A percentile table read from its JSON. Raises ValueError saying what is wrong."""
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("a delay table needs a version")
    kinds = data.get("percentiles")
    if not isinstance(kinds, dict) or set(kinds) != set(KINDS):  # pyright: ignore[reportUnknownArgumentType]
        raise ValueError(f"{version}: percentiles for exactly {', '.join(KINDS)}")
    table: dict[str, tuple[int, ...]] = {}
    for kind in KINDS:
        points = kinds[kind]  # pyright: ignore[reportUnknownVariableType]
        if (
            not isinstance(points, list)
            or len(points) != POINTS  # pyright: ignore[reportUnknownArgumentType]
            or not all(type(p) is int and p >= 0 for p in points)  # pyright: ignore[reportUnknownVariableType]
            or points != sorted(points)  # pyright: ignore[reportUnknownArgumentType]
        ):
            raise ValueError(
                f"{version} {kind}: {POINTS} whole microseconds, none below zero, in order"
            )
        table[kind] = tuple(points)  # pyright: ignore[reportUnknownArgumentType]
    stand_in = data.get("stand_in", False)
    if not isinstance(stand_in, bool):
        raise ValueError(f"{version}: stand_in is true or false")
    return DelayTable(version, table, stand_in)


def _folder() -> Traversable:
    """Where the percentile tables are: ``fish_agents/delay_tables``."""
    return resources.files("fish_agents") / _TABLES


def load(version: str) -> DelayTable:
    """The table ``version``: ``UNIFORM``, or a file in ``fish_agents/delay_tables``."""
    if version == UNIFORM:
        return DelayTable(UNIFORM)
    path = _folder() / f"{version}.json"
    if not path.is_file():
        raise ValueError(f"no delay table {version!r}")
    table = check(json.loads(path.read_text()))
    if table.version != version:
        raise ValueError(f"{version}.json says it is {table.version!r}")
    return table


def versions() -> list[str]:
    """Every table there is."""
    files = sorted(
        p.name.removesuffix(".json") for p in _folder().iterdir() if p.name.endswith(".json")
    )
    return [UNIFORM, *files]


def from_report(figures: Mapping[str, object], version: str, source: str) -> dict[str, object]:
    """A percentile table's JSON from the pilot report's ``--out`` file: each kind's
    percentiles, with any below zero (an input that arrived while the update it answered was
    still going out) raised to zero. Refuses a kind with fewer than ``MIN_TIMES`` times."""
    times = figures.get("response_times_us")
    if not isinstance(times, dict):
        raise ValueError("not a pilot report: no response_times_us")
    percentiles: dict[str, list[int]] = {}
    for kind in KINDS:
        entry = times.get(kind)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(entry, dict):
            raise ValueError(f"the report has no response times for {kind}")
        count, points = entry.get("count"), entry.get("percentiles")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(count, int) or count < MIN_TIMES:
            raise ValueError(
                f"{KINDS[kind]}: {count} response times, too few for a table (at least {MIN_TIMES})"
            )
        if not isinstance(points, list) or len(points) != POINTS:  # pyright: ignore[reportUnknownArgumentType]
            raise ValueError(f"{kind}: the report should have {POINTS} percentiles")
        percentiles[kind] = [max(0, int(p)) for p in points]  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    data: dict[str, object] = {
        "version": version,
        "source": source,
        "counts": {kind: times[kind]["count"] for kind in KINDS},  # pyright: ignore[reportUnknownMemberType]
        "percentiles": percentiles,
    }
    check(data)
    return data
