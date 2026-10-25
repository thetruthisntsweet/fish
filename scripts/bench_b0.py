"""Performance smoke (Implementation Environment §9, §13): play B0-vs-B0 games and time them.

Run: ``uv run python scripts/bench_b0.py --games 1000 --json performance.json``.

Plays ``--games`` environment games of six B0 agents (``fish_agents.b0``, b0-v1) from seeds
``--first-seed`` onward, then times ``fish_rules.action_index.legal_mask`` for every seat at
every state of the first ``--mask-games`` games (seats that may not act included, as the
environment computes them too). Prints a short Markdown table, and with ``--json`` writes
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
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent
from fish_rules.version import RULESET_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play B0-vs-B0 games and time them.")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--mask-games", type=int, default=20)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if args.games < 1 or args.mask_games < 1:
        parser.error("--games and --mask-games must be at least 1")

    agents = [B0()] * 6
    started = time.perf_counter()
    records = [play_game(agents, args.first_seed + i) for i in range(args.games)]
    seconds = time.perf_counter() - started

    actions: list[int] = []
    asks: list[int] = []
    calls: list[int] = []
    unfinished = 0
    mask_states = []
    for i, record in enumerate(records):
        seed = int(str(record["seed"]))
        recorded = record["actions"]
        assert isinstance(recorded, list)
        game_actions = [action_from_data(data) for data in recorded]
        states = []
        game_asks = game_calls = 0
        for state, step in replay(seed, game_actions):
            game_asks += sum(isinstance(r, AskEvent) for r in step)
            game_calls += sum(isinstance(r, CallEvent) for r in step)
            if i < args.mask_games:
                states.append(state)
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

    result = {
        "agent": B0_VERSION,
        "ruleset": RULESET_VERSION,
        "games": args.games,
        "first_seed": args.first_seed,
        "seconds": round(seconds, 3),
        "games_per_second": round(args.games / seconds, 2),
        "mask_microseconds": round(1e6 * mask_seconds / masks, 2),
        "masks_timed": masks,
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
