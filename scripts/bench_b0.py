"""Performance smoke (Implementation Environment §9, §13): play B0-vs-B0 and B1-vs-B1 games
and time them.

Run: ``uv run python scripts/bench_b0.py --games 1000 --json performance.json``.

Plays ``--games`` environment games of six B0 agents (``fish_agents.b0``, b0-v1) from seeds
``--first-seed`` onward, then times ``fish_rules.action_index.legal_mask`` for every seat at
every state of the first ``--mask-games`` games (seats that may not act included, as the
environment computes them too), and Layer 1 (``fish_rules.deduce.solve.deduce``, full
memory) for every seat after every event of the first ``--deduce-games`` games, as an agent
using it would at each decision. Then it plays ``--b1-games`` games of six B1 agents with full
memory (``fish_agents.b1``, b1-v1) from the same seeds and times every B1 decision, Layer 1
included: the website's bots (T3.5) make one such decision per action. Prints a short Markdown
table, and with ``--json`` writes the numbers to a file, so CI can keep them as an artifact and
slowdowns show up over time.

Timings vary by machine; compare runs on the same runner type. The game statistics
(actions, asks, calls) do not vary: a change there is a change in behaviour, not speed.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

from fish_agents.b0 import B0, B0_VERSION
from fish_agents.b1 import B1_VERSION, b1
from fish_agents.memory import FULL
from fish_agents.play import play_game
from fish_rules.action_index import legal_mask
from fish_rules.cards import SEATS
from fish_rules.codec import action_from_data
from fish_rules.deduce.solve import deduce
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.rng import SplitMix64
from fish_rules.state import State
from fish_rules.version import RULESET_VERSION
from fish_rules.view import PlayerView, latest_event, project


class TimedB1:
    """B1 with full memory, timing each decision (shown every view, as ``play_game`` does)."""

    def __init__(self) -> None:
        self.agent = b1(FULL)
        self.seconds: list[float] = []

    def observe(self, view: PlayerView) -> None:
        self.agent.observe(view)

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        started = time.perf_counter()
        chosen = self.agent.act(view, rng)
        self.seconds.append(time.perf_counter() - started)
        return chosen


def p99(times: list[float]) -> float:
    """The 99th percentile of ``times``, in microseconds."""
    ordered = sorted(times)
    return round(1e6 * ordered[int(0.99 * (len(ordered) - 1))], 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play B0-vs-B0 games and time them.")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--mask-games", type=int, default=20)
    parser.add_argument("--deduce-games", type=int, default=20)
    parser.add_argument("--b1-games", type=int, default=20)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if min(args.games, args.mask_games, args.deduce_games, args.b1_games) < 1:
        parser.error("--games, --mask-games, --deduce-games and --b1-games must be at least 1")

    agents = [B0()] * 6
    started = time.perf_counter()
    records = [play_game(agents, args.first_seed + i) for i in range(args.games)]
    seconds = time.perf_counter() - started

    actions: list[int] = []
    asks: list[int] = []
    calls: list[int] = []
    unfinished = 0
    mask_states = []
    points: list[tuple[State, Event | None, tuple[Event, ...]]] = []
    for i, record in enumerate(records):
        seed = int(str(record["seed"]))
        recorded = record["actions"]
        assert isinstance(recorded, list)
        game_actions = [action_from_data(data) for data in recorded]
        states = []
        game_asks = game_calls = 0
        last: Event | None = None
        events: list[Event] = []
        for state, step in replay(seed, game_actions):
            game_asks += sum(isinstance(r, AskEvent) for r in step)
            game_calls += sum(isinstance(r, CallEvent) for r in step)
            if i < args.mask_games:
                states.append(state)
            new = [r for r in step if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
            last = latest_event(step, last)
            events += new
            if new and i < args.deduce_games:
                points.append((state, last, tuple(events)))
        actions.append(len(game_actions))
        asks.append(game_asks)
        calls.append(game_calls)
        unfinished += record["outcome"] != "finished"
        mask_states.extend(states)

    masks = 0
    mask_started = time.perf_counter()
    for state in mask_states:
        for seat in SEATS:
            legal_mask(state, seat)
            masks += 1
    mask_seconds = time.perf_counter() - mask_started

    deduce_times: list[float] = []
    for state, last, seen in points:
        for seat in SEATS:
            view = project(state, seat, last)
            deduce_started = time.perf_counter()
            deduce(view, seen)
            deduce_times.append(time.perf_counter() - deduce_started)

    b1_seconds = 0.0
    b1_actions: list[int] = []
    b1_unfinished = 0
    b1_times: list[float] = []
    for i in range(args.b1_games):
        timed = TimedB1()
        b1_started = time.perf_counter()
        record = play_game([timed] * 6, args.first_seed + i)
        b1_seconds += time.perf_counter() - b1_started
        recorded = record["actions"]
        assert isinstance(recorded, list)
        b1_actions.append(len(recorded))
        b1_unfinished += record["outcome"] != "finished"
        b1_times += timed.seconds

    result = {
        "agent": B0_VERSION,
        "ruleset": RULESET_VERSION,
        "games": args.games,
        "first_seed": args.first_seed,
        "seconds": round(seconds, 3),
        "games_per_second": round(args.games / seconds, 2),
        "mask_microseconds": round(1e6 * mask_seconds / masks, 2),
        "masks_timed": masks,
        "deduce_microseconds": round(1e6 * statistics.fmean(deduce_times), 1),
        "deduce_p99_microseconds": p99(deduce_times),
        "deductions_timed": len(deduce_times),
        "mean_actions": round(statistics.fmean(actions), 2),
        "mean_asks": round(statistics.fmean(asks), 2),
        "mean_calls": round(statistics.fmean(calls), 2),
        "unfinished": unfinished,
        "b1_agent": B1_VERSION,
        "b1_games": args.b1_games,
        "b1_games_per_second": round(args.b1_games / b1_seconds, 2),
        "b1_decision_microseconds": round(1e6 * statistics.fmean(b1_times), 1),
        "b1_decision_p99_microseconds": p99(b1_times),
        "b1_decisions_timed": len(b1_times),
        "b1_mean_actions": round(statistics.fmean(b1_actions), 2),
        "b1_unfinished": b1_unfinished,
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "commit": os.environ.get("GITHUB_SHA", "local"),
    }
    print("| Measure | Value |\n|---|---|")
    for key, value in result.items():
        print(f"| {key} | {value} |")
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
