"""B1's evaluation and nightly soak (T5.2): how B1 plays at each memory setting, with every
game checked.

Run: ``uv run python scripts/eval_b1.py --games 200 --workers 4 --json eval-b1.json``.

For each memory setting (``--memories``, default full, last-8, last-2 and none) B1
(``fish_agents.b1``, b1-v1) plays ``--games`` environment games from seeds ``--first-seed``
onward in each matchup:

- ``b0``: B1 against three B0s, each seed played twice, with B1 as team 0 and as team 1;
- ``full``: B1 against three full-memory B1s, the same way (not for full memory itself);
- ``self``: six B1s with the same memory.

It reports, for each matchup and setting, how many games finished (R.8.2: a game stopped at
1,000 asks has no result), the share of finished games B1 won with a 95% Wilson interval, the
mean number of asks, and B1's calls: those it chose because Layer 1 proved them, and those it
had to make (run-out, or a turn with no legal ask) with how many of them were right.

It checks every game: every R.9 invariant at every state and a record that replays, as the B0
soak does (``scripts/soak_b0.py``), and that every call B1 chose because it was proved was
right. Exits 1 and prints the first failing game if any check fails; rerun a game with
``--first-seed SEED --games 1``. Prints a Markdown table, and with ``--json`` writes the
numbers to a file.
"""

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from soak_b0 import InvariantError, check_record

from fish_agents.b0 import B0
from fish_agents.b1 import B1_VERSION, b1, certain_calls
from fish_agents.base import Agent
from fish_agents.memory import FULL, NONE, MemorySetting
from fish_agents.play import play_game
from fish_rules.action_index import CALL_BASE, PASS_INDEX
from fish_rules.cards import NUM_SETS, Seat, SetId, team_of
from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import CallEvent
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase
from fish_rules.version import RULESET_VERSION
from fish_rules.view import PlayerView

MEMORIES = {"full": FULL, "last-8": MemorySetting.last_k(8), "last-2": MemorySetting.last_k(2)}
MEMORIES["none"] = NONE
MATCHUPS = ("b0", "full", "self")
"""B1's opponents: three B0s, three full-memory B1s, or B1s with its own memory."""


class Checked:
    """B1 with memory, noting each call it chooses because Layer 1 proves it."""

    def __init__(self, setting: MemorySetting) -> None:
        self.agent = b1(setting)
        self.proved: set[tuple[Seat, SetId]] = set()

    def observe(self, view: PlayerView) -> None:
        self.agent.observe(view)

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        chosen = self.agent.act(view, rng)
        if view.phase in (Phase.WINDOW, Phase.TURN) and CALL_BASE <= chosen < PASS_INDEX:
            set_id = (
                chosen - CALL_BASE
            ) % NUM_SETS  # a call (162 + set) or declaration (171 + set)
            deduction = self.agent.memory(view.seat).deduction
            if set_id in certain_calls(view.seat, deduction, view.scored_by):
                self.proved.add((view.seat, set_id))
        return chosen


@dataclass(frozen=True, slots=True)
class Game:
    """One evaluation game: B1 with ``memory`` as ``team`` against ``matchup``."""

    matchup: str
    memory: str
    team: int
    seed: int
    finished: bool = False
    won: bool = False
    asks: int = 0
    proved_calls: int = 0
    forced_calls: int = 0
    forced_right: int = 0
    failure: str | None = None


def play(game: Game) -> Game:
    """Play and check ``game``; the same game with its results, or its failure."""
    try:
        return _play(game)
    except Exception as error:  # report any failure, with its game
        why = f"{type(error).__name__}: {error}"
        return Game(game.matchup, game.memory, game.team, game.seed, failure=why)


def tally(
    calls: list[CallEvent], proved: set[tuple[Seat, SetId]], mine: list[CallEvent]
) -> tuple[int, int]:
    """Check that every call in ``proved`` was right; of the other calls in ``mine`` (the
    tested B1's), how many there were and how many were right."""
    forced = right = 0
    for call in calls:
        correct = call.correct
        if (call.caller, call.set_id) in proved:
            if not correct:
                raise InvariantError(f"B1 at seat {call.caller} proved set {call.set_id}, wrongly")
        elif call in mine:
            forced += 1
            right += correct
    return forced, right


def _play(game: Game) -> Game:
    tested = Checked(MEMORIES[game.memory])
    full = Checked(FULL) if game.matchup == "full" else None
    seated: Agent = tested
    other: Agent = full or (tested if game.matchup == "self" else B0())
    agents = [seated] * 3 + [other] * 3
    if game.team == 1:
        agents = agents[3:] + agents[:3]
    record = play_game(agents, game.seed)
    asks, _, finished = check_record(game.seed, record)
    recorded = record["actions"]
    assert isinstance(recorded, list)
    actions = [action_from_data(data) for data in recorded]
    calls = [r for _, step in replay(game.seed, actions) for r in step if isinstance(r, CallEvent)]
    proved = tested.proved | (full.proved if full is not None else set())
    mine = [c for c in calls if team_of(c.caller) == game.team or game.matchup == "self"]
    forced, right = tally(calls, proved, mine)
    winner = record["winner"]
    return Game(
        game.matchup,
        game.memory,
        game.team,
        game.seed,
        finished=finished,
        won=winner == game.team,
        asks=asks,
        proved_calls=sum((c.caller, c.set_id) in tested.proved for c in mine),
        forced_calls=forced,
        forced_right=right,
    )


def wilson(wins: int, games: int) -> tuple[float, float]:
    """The 95% Wilson score interval for ``wins`` out of ``games``."""
    if games == 0:
        return 0.0, 1.0
    z = 1.959964
    share = wins / games
    centre = (share + z * z / (2 * games)) / (1 + z * z / games)
    half = z * math.sqrt(share * (1 - share) / games + z * z / (4 * games * games))
    return max(0.0, centre - half / (1 + z * z / games)), min(
        1.0, centre + half / (1 + z * z / games)
    )


def games_to_play(memories: list[str], first: int, count: int) -> list[Game]:
    out: list[Game] = []
    for matchup in MATCHUPS:
        for memory in memories:
            if matchup == "full" and memory == "full":
                continue  # the same as six full-memory B1s
            teams = (0,) if matchup == "self" else (0, 1)
            out += [Game(matchup, memory, t, s) for s in range(first, first + count) for t in teams]
    return out


def summary(results: list[Game]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Game]] = defaultdict(list)
    for game in results:
        groups[game.matchup, game.memory].append(game)
    rows: list[dict[str, object]] = []
    for (matchup, memory), games in groups.items():
        finished = [g for g in games if g.finished]
        wins = sum(g.won for g in finished)
        low, high = wilson(wins, len(finished))
        row: dict[str, object] = {
            "matchup": matchup,
            "memory": memory,
            "games": len(games),
            "finished": len(finished),
            "won": None if matchup == "self" else wins,
            "win_share": None
            if matchup == "self" or not finished
            else round(wins / len(finished), 3),
            "win_interval": None if matchup == "self" else [round(low, 3), round(high, 3)],
            "mean_asks": round(sum(g.asks for g in games) / len(games), 1),
            "proved_calls": sum(g.proved_calls for g in games),
            "forced_calls": sum(g.forced_calls for g in games),
            "forced_right": sum(g.forced_right for g in games),
        }
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate B1 and check every game.")
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--memories", default=",".join(MEMORIES))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if min(args.games, args.workers) < 1:
        parser.error("--games and --workers must be at least 1")
    memories = args.memories.split(",")
    unknown = [m for m in memories if m not in MEMORIES]
    if unknown:
        parser.error(f"--memories are some of {', '.join(MEMORIES)}, not {unknown[0]!r}")

    planned = games_to_play(memories, args.first_seed, args.games)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(play, planned, chunksize=4))
    seconds = time.perf_counter() - started
    failures = [g for g in results if g.failure is not None]
    rows = summary([g for g in results if g.failure is None])
    first = min(failures, key=lambda g: g.seed) if failures else None
    result: dict[str, object] = {
        "agent": B1_VERSION,
        "ruleset": RULESET_VERSION,
        "games_per_matchup": args.games,
        "first_seed": args.first_seed,
        "games_played": len(results),
        "seconds": round(seconds, 1),
        "rows": rows,
        "failures": len(failures),
        "first_failure": None if first is None else asdict(first),
    }
    print("| Against | B1 memory | Games | Finished | B1 won | 95% interval | Mean asks "
          "| Proved calls | Forced calls (right) |")  # fmt: skip
    print("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        won = "—" if row["won"] is None else f"{row['won']} ({row['win_share']})"
        interval = row["win_interval"]
        shown = "—" if interval is None else f"{interval[0]} to {interval[1]}"  # pyright: ignore[reportIndexIssue]
        print(
            f"| {row['matchup']} | {row['memory']} | {row['games']} | {row['finished']} | {won} "
            f"| {shown} | {row['mean_asks']} | {row['proved_calls']} "
            f"| {row['forced_calls']} ({row['forced_right']}) |"
        )
    print(f"\n{len(results)} games in {seconds:.0f} s; failures: {len(failures)}")
    if first is not None:
        print(f"first failure: {first.matchup} {first.memory} team {first.team} "
              f"seed {first.seed}: {first.failure}")  # fmt: skip
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
