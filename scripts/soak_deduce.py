"""Nightly Layer 1 soak (T2.7): deduce at every event of many B0 games, and check it.

Run: ``uv run python scripts/soak_deduce.py --games 3000 --workers 4``.

Plays ``--games`` environment games of six B0 agents from seeds ``--first-seed`` onward,
spread over ``--workers`` processes. In every game, after every event, for every seat and the
public view, with full memory (``fish_rules.deduce``):

- every card's true holder is among the seats named, and cards out of play have none;
- the example deal, moved forward, has every seat's hand size now;
- at one point in ``--probe`` (drawn from the game's seed), one seat named for a card that
  does not hold it is tried: a deal with the card there must exist, and playing the game's
  actions from that deal in the engine must show the observer exactly what it was shown (the
  same public records, and for a seat, the same view after every action).

Every certain miss (``fish_rules.deduce.games.certain_misses``) must also miss. The tests
(``test_deduce_*.py``) check the same on random play; this checks it on B0's play, at a scale
that only fits in a nightly run.

Exits 1 and prints the first failing seed and why if any check fails; one game is rerun
with ``--first-seed SEED --games 1``. Prints a short Markdown table, and with ``--json``
writes it to a file.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

from fish_agents.b0 import B0, B0_VERSION
from fish_agents.play import play_game
from fish_rules.cards import CARDS, SEATS, Hand, Seat
from fish_rules.codec import action_from_data
from fish_rules.deduce.games import certain_misses
from fish_rules.deduce.solve import Deduction, deduce, example_deal
from fish_rules.engine import apply
from fish_rules.events import Action, AskEvent, CallEvent, ChoiceEvent, Event, Record, Visibility
from fish_rules.rng import SplitMix64
from fish_rules.state import State, new_game
from fish_rules.version import RULESET_VERSION
from fish_rules.view import latest_event, project


class DeductionError(Exception):
    """Layer 1 said something that is not so."""


def require(condition: bool, why: str) -> None:
    if not condition:
        raise DeductionError(why)


def holder(hands: tuple[Hand, ...], card: int) -> Seat | None:
    return next((seat for seat in SEATS if card in hands[seat]), None)


def public(records: tuple[Record, ...]) -> tuple[Record, ...]:
    return tuple(r for r in records if r.visibility is Visibility.PUBLIC)


def replays_the_same(
    seed: int, actions: list[Action], upto: int, observer: Seat | None, deal: tuple[Hand, ...]
) -> None:
    """Play ``actions[:upto]`` from ``deal`` and from the true deal side by side: the
    observer must be shown the same at every step."""
    true_state = new_game(seed)
    state = replace(true_state, hands=deal)
    last: Event | None = None
    for action in actions[:upto]:
        state, records = apply(state, action)
        true_state, true_records = apply(true_state, action)
        require(public(records) == public(true_records), "another deal changes a public record")
        last = latest_event(true_records, last)
        if observer is not None:
            require(
                project(state, observer, last) == project(true_state, observer, last),
                f"another deal changes what seat {observer} is shown",
            )


def check_point(d: Deduction, state: State, where: str) -> None:
    for card in CARDS:
        truth = holder(state.hands, card)
        if truth is None:
            require(d.holders[card] == 0, f"{where}: card {card} is out of play but has holders")
        else:
            require(bool(d.holders[card] >> truth & 1), f"{where}: card {card}'s holder is missing")
    sizes = tuple(len(hand) for hand in d.example_now())
    require(sizes == tuple(len(hand) for hand in state.hands), f"{where}: the example's sizes")


def check_game(seed: int, probe: int) -> tuple[int, int, int]:
    """Deduce at every event of the B0 game from ``seed`` and check it. Returns (deductions,
    deals replayed, certain misses); raises ``DeductionError`` (or Layer 1's own error)."""
    rng = SplitMix64(seed)
    recorded = play_game([B0()] * 6, seed)["actions"]
    assert isinstance(recorded, list)
    actions = [action_from_data(data) for data in recorded]
    state, last = new_game(seed), None
    dealt = state.hands
    events: list[Event] = []
    deductions = replayed = 0
    for k, action in enumerate([None, *actions]):
        if action is not None:
            state, records = apply(state, action)
            last = latest_event(records, last)
            new = [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
            if not new:
                continue
            events += new
        for observer in (*SEATS, None):
            view = project(state, 0 if observer is None else observer, last)
            d = deduce(view, events, use_hand=observer is not None)
            deductions += 1
            where = f"after action {k}, {'public' if observer is None else f'seat {observer}'}"
            check_point(d, state, where)
            if rng.below(probe):
                continue
            options = [
                (card, seat)
                for card in CARDS
                for seat in SEATS
                if d.anchor[card] >> seat & 1 and holder(dealt, card) != seat
            ]
            if options:
                card, seat = rng.choice(options)
                deal = example_deal(d.constraints, {card: seat})
                require(deal is not None, f"{where}: no deal puts card {card} with seat {seat}")
                assert deal is not None
                replays_the_same(seed, actions, k, observer, deal)
                replayed += 1
    misses = certain_misses(new_game(seed), actions)
    require(all(not event.success for event in misses), "a certain miss succeeded")
    return deductions, replayed, len(misses)


def check_range(first: int, count: int, probe: int) -> tuple[int, int, int, int, str | None]:
    """Check ``count`` games from seed ``first``. Returns (games, deductions, deals replayed,
    certain misses, the first failure as "seed: why" or None); stops at the first failure."""
    deductions = replayed = misses = 0
    for seed in range(first, first + count):
        try:
            game_deductions, game_replayed, game_misses = check_game(seed, probe)
        except Exception as error:  # report any failure, with its seed
            failure = f"{seed}: {type(error).__name__}: {error}"
            return seed - first, deductions, replayed, misses, failure
        deductions += game_deductions
        replayed += game_replayed
        misses += game_misses
    return count, deductions, replayed, misses, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deduce at every event of B0 games and check.")
    parser.add_argument("--games", type=int, default=3_000)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk", type=int, default=50)
    parser.add_argument("--probe", type=int, default=20, help="replay a deal at 1 point in N")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if min(args.games, args.workers, args.chunk, args.probe) < 1:
        parser.error("--games, --workers, --chunk and --probe must be at least 1")

    chunks = [
        (start, min(args.chunk, args.first_seed + args.games - start))
        for start in range(args.first_seed, args.first_seed + args.games, args.chunk)
    ]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        firsts, counts = zip(*chunks, strict=True)
        results = list(pool.map(check_range, firsts, counts, [args.probe] * len(chunks)))
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
        "deductions": sum(r[1] for r in results),
        "deals_replayed": sum(r[2] for r in results),
        "certain_misses": sum(r[3] for r in results),
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
