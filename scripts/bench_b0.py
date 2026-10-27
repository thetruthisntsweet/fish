"""Performance smoke (Implementation Environment §9, §13): play B0-vs-B0 games and time them.

Run: ``uv run python scripts/bench_b0.py --games 1000 --json performance.json``.

Plays ``--games`` environment games of six B0 agents (``fish_agents.b0``, b0-v1) from seeds
``--first-seed`` onward, then times ``fish_rules.action_index.legal_mask`` for every seat at
every state of the first ``--mask-games`` games (seats that may not act included, as the
environment computes them too), and Layer 1 (``fish_rules.deduce.solve.deduce``, full
memory) for every seat after every event of the first ``--deduce-games`` games, as an agent
using it would at each decision. Prints a short Markdown table, and with ``--json`` writes
the numbers to a file, so CI can keep them as an artifact and slowdowns show up over time.

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
from fish_agents.play import play_game
from fish_rules.action_index import legal_mask
from fish_rules.cards import SEATS
from fish_rules.codec import action_from_data
from fish_rules.deduce.solve import deduce
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.state import State
from fish_rules.version import RULESET_VERSION
from fish_rules.view import latest_event, project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play B0-vs-B0 games and time them.")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--mask-games", type=int, default=20)
    parser.add_argument("--deduce-games", type=int, default=20)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if min(args.games, args.mask_games, args.deduce_games) < 1:
        parser.error("--games, --mask-games and --deduce-games must be at least 1")

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
    deduce_times.sort()

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
        "deduce_p99_microseconds": round(
            1e6 * deduce_times[int(0.99 * (len(deduce_times) - 1))], 1
        ),
        "deductions_timed": len(deduce_times),
        "mean_actions": round(statistics.fmean(actions), 2),
        "mean_asks": round(statistics.fmean(asks), 2),
        "mean_calls": round(statistics.fmean(calls), 2),
        "unfinished": unfinished,
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
