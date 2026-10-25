"""Nightly soak (Implementation Environment §9): many B0-vs-B0 games, every R.9 check.

Run: ``uv run python scripts/soak_b0.py --games 100000 --workers 4``.

Plays ``--games`` environment games of six B0 agents (``fish_agents.b0``) from seeds
``--first-seed`` onward, spread over ``--workers`` processes, and checks every game:

- at every state, the rule-level invariants of ``fish_rules.state.check_consistency``
  (cards conserved, hands sorted, the phase matches what is pending);
- R.9: the turn never falls to a player without cards; the current player can always act;
  someone can act until the game is over; at most nine calls occur; a correct call lets the
  caller's team choose who moves next, and the team that scored chooses;
- event numbers run 0, 1, 2, ... (docs/determinism.md §8);
- the game ends, a finished game's winner has five or more sets, and the record replays to
  the same final state (``fish_rules.record``).

Exits 1 and prints the first failing seed and why if any check fails; a single game is
rerun with ``--first-seed SEED --games 1``. Prints a short Markdown table, and with
``--json`` writes it to a file.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import pairwise
from pathlib import Path

from fish_agents.b0 import B0, B0_VERSION
from fish_agents.play import play_game
from fish_rules.cards import SETS, team_of
from fish_rules.codec import action_from_data
from fish_rules.engine import acting_seats, legal_actions, replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Record
from fish_rules.record import replay_record
from fish_rules.state import SETS_TO_WIN, Outcome, Phase, check_consistency, state_hash
from fish_rules.version import RULESET_VERSION


class InvariantError(Exception):
    """A game broke a rule-level invariant."""


def require(condition: bool, why: str) -> None:
    if not condition:
        raise InvariantError(why)


def check_game(seed: int) -> tuple[int, int, bool]:
    """Play and check the B0 game from ``seed``. Returns (asks, calls, finished); raises
    ``InvariantError`` (or the engine's own error) on any broken invariant."""
    record = play_game([B0()] * 6, seed)
    recorded = record["actions"]
    assert isinstance(recorded, list)
    actions = [action_from_data(data) for data in recorded]
    records: list[Record] = []
    state = None
    for state, step in replay(seed, actions):
        records.extend(step)
        try:
            check_consistency(state)
        except ValueError as error:
            raise InvariantError(str(error)) from None
        if state.phase in (Phase.TURN, Phase.RUNOUT):
            require(state.current is not None, "no current player on a turn")
            assert state.current is not None
            require(bool(legal_actions(state, state.current)), "R.9: the current player cannot act")
        if state.phase is Phase.TURN:
            assert state.current is not None
            require(
                bool(state.hands[state.current]), "R.9: the turn fell to a player without cards"
            )
        window_complete = state.window is not None and all(state.window.responded)
        if state.phase is not Phase.OVER and not window_complete:
            require(bool(acting_seats(state)), "no one can act")
    require(state is not None and state.phase is Phase.OVER, "the game did not end")
    assert state is not None
    calls = [r for r in records if isinstance(r, CallEvent)]
    require(len(calls) <= len(SETS), "R.9: more than nine calls")
    numbers = [r.number for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
    require(numbers == list(range(state.events)), "event numbers do not run 0, 1, 2, ...")
    finished = state.outcome is Outcome.FINISHED
    if finished:
        winner = state.winner()
        require(winner is not None, "a finished game has no winner")
        assert winner is not None
        require(state.score(winner) >= SETS_TO_WIN > state.score(1 - winner), "R.7.1: bad score")
    for before, after in pairwise(records):
        if isinstance(before, CallEvent) and isinstance(after, ChoiceEvent):
            require(after.team == before.scored_by, "R.5.1: the wrong team chose")
            if before.correct:
                require(
                    after.team == team_of(before.caller), "R.9: initiative after a correct call"
                )
    require(state_hash(replay_record(record)) == state_hash(state), "the record does not replay")
    asks = sum(isinstance(r, AskEvent) for r in records)
    return asks, len(calls), finished


def check_range(first: int, count: int) -> tuple[int, int, int, int, str | None]:
    """Check ``count`` games from seed ``first``. Returns (games, asks, calls, unfinished,
    the first failure as "seed: why" or None); stops at the first failure."""
    asks = calls = unfinished = 0
    for seed in range(first, first + count):
        try:
            game_asks, game_calls, finished = check_game(seed)
        except Exception as error:  # report any failure, with its seed
            return seed - first, asks, calls, unfinished, f"{seed}: {type(error).__name__}: {error}"
        asks += game_asks
        calls += game_calls
        unfinished += not finished
    return count, asks, calls, unfinished, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play B0-vs-B0 games and check every one.")
    parser.add_argument("--games", type=int, default=100_000)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk", type=int, default=500)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if min(args.games, args.workers, args.chunk) < 1:
        parser.error("--games, --workers and --chunk must be at least 1")

    chunks = [
        (start, min(args.chunk, args.first_seed + args.games - start))
        for start in range(args.first_seed, args.first_seed + args.games, args.chunk)
    ]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(check_range, *zip(*chunks, strict=True)))
    seconds = time.perf_counter() - started
    failures = [failure for *_, failure in results if failure is not None]
    games = sum(r[0] for r in results)
    result = {
        "agent": B0_VERSION,
        "ruleset": RULESET_VERSION,
        "games_checked": games,
        "first_seed": args.first_seed,
        "workers": args.workers,
        "seconds": round(seconds, 1),
        "games_per_second": round(games / seconds, 1),
        "mean_asks": round(sum(r[1] for r in results) / max(games, 1), 2),
        "mean_calls": round(sum(r[2] for r in results) / max(games, 1), 2),
        "unfinished": sum(r[3] for r in results),
        "failures": len(failures),
        "first_failure": min(failures, key=lambda f: int(f.split(":")[0])) if failures else None,
    }
    print("| Measure | Value |\n|---|---|")
    for key, value in result.items():
        print(f"| {key} | {value} |")
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
