"""Minimum detectable effects of the primary metrics, from the pilot (T4.2; Research Questions
§5.4; docs/mde.md). Aggregates only, and nothing is written to the database.

    python -m fish_server.mde --since 2026-12-01

Run it in ``fish-staging``'s Shell after the last pilot night, and copy what it prints into
``docs/mde.md`` before the study opens. The primary metrics need B2 and B3, which do not exist
yet, so each is stood in for by a proxy computed from the same games, whose spread from game
to game sets the effect the study could detect. All three are recomputed when B2 and B3 exist
(T6.4):

- **RQ1, information gain** (bits per card): Layer 1's log loss, every seat's belief after
  every event, each card it does not hold whose place is not public, scored against its true
  holder with the possible holders weighted equally (the floor model). Its spread across games
  stands in for the spread of the B2 - B3 difference, which, being paired on the same cards,
  should be smaller: so the MDE is on the cautious side.
- **RQ2, mean leakage** (bits per action): a hand-count policy, which asks for a set in
  proportion to how many of its cards the asker holds, compared with the same policy on the
  counts the public view expects that seat to hold (Layer 1's public deduction, possible
  holders weighted equally). Asks only.
- **RQ3, cross-play gap** (win rate): the difference between two win rates, each from its own
  games, at the pilot's spread of who wins a finished game.

Each MDE is the difference a two-sided test at 5% would find with 80% power:
``(z(0.975) + z(0.80)) x SE``, with the SE from a game-level bootstrap (10,000 resamples, as
the analysis will use) at the pilot's number of games, scaled to ``n`` games by
``sqrt(pilot games / n)``.
"""

import argparse
import math
import random
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist
from typing import Final

from sqlalchemy import Connection, Engine, create_engine, pool

from fish_rules.cards import SEATS, SETS, set_cards, set_of
from fish_rules.corpus import CorpusGame, read_corpus_record
from fish_rules.deduce.solve import Deduction, deduce
from fish_rules.engine import apply
from fish_rules.events import Ask, AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.state import State, new_game
from fish_rules.view import latest_event, project
from fish_server.corpus_export import Summary, records
from fish_server.pilot_report import chosen
from fish_server.settings import database_url

Z: Final = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.80)
"""2.80: two-sided 5%, 80% power."""
RESAMPLES: Final = 10_000
SEED: Final = 20261208
"""The bootstrap's seed, so a rerun prints the same."""
GAMES: Final = (150, 1_000)
"""The games each MDE is given for: about one test set's primary-set games (§5.1: each test
set is about 15% of the corpus), and the corpus's target."""
FEW: Final = 10
"""Fewer finished games than this, and the report says its figures are unreliable."""


@dataclass(frozen=True, slots=True)
class GameFigures:
    """One game's proxies, as sums and counts, so games pool as the analysis pools them."""

    loss_bits: float
    cards: int
    leak_bits: float
    asks: int
    team_0_won: bool | None
    """None unless the game finished (R.7.1): win rates count finished games."""


# ---------------------------------------------------------------- per game


def _scored(state: State, last: Event | None, events: Sequence[Event]) -> tuple[float, int]:
    """Layer 1's log loss, summed over every seat's hidden cards whose place is not public."""
    public = deduce(project(state, 0, last), events, use_hand=False)
    holder = {card: seat for seat, hand in enumerate(state.hands) for card in hand}
    hidden = [card for card in holder if public.known(card) is None]
    loss, cards = 0.0, 0
    for seat in SEATS:
        mine = deduce(project(state, seat, last), events)
        for card in hidden:
            if holder[card] != seat:
                possible = mine.possible(card)
                assert holder[card] in possible  # Layer 1 is exact
                loss += math.log2(len(possible))
                cards += 1
    return loss, cards


def _leak(state: State, ask: Ask, public: Deduction) -> float:
    """The hand-count policy's leakage for ``ask``, in bits: how much likelier its set was
    under the asker's true counts than under the counts the public view expects."""
    seat, hand = ask.seat, set(state.hands[ask.seat])
    askable = [s for s in SETS if 0 < sum(c in hand for c in set_cards(s)) < 6]
    true = {s: sum(c in hand for c in set_cards(s)) for s in askable}
    expected = {
        s: sum(1 / len(p) for c in set_cards(s) if seat in (p := public.possible(c)))
        for s in askable
    }
    asked = set_of(ask.card)
    expected[asked] = max(expected[asked], 1.0)  # the ask was legal: it holds one at least
    p_true = true[asked] / sum(true.values())
    p_public = expected[asked] / sum(expected.values())
    return math.log2(p_true / p_public)


def figures(game: CorpusGame) -> GameFigures:
    """``game``'s proxies: at the deal and after every event (T1.1 §1), and at every ask."""
    state, last = new_game(game.seed), None
    events: list[Event] = []
    loss, cards = _scored(state, last, events)
    leak, asks = 0.0, 0
    for index, step in enumerate(game.steps):
        action = step.action
        if isinstance(action, Ask) and game.person_acts(action.seat, index):
            public = deduce(project(state, 0, last), events, use_hand=False)
            leak += _leak(state, action, public)
            asks += 1
        state, records_ = apply(state, action)
        last = latest_event(records_, last)
        produced = [r for r in records_ if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
        if produced:
            events += produced
            more, counted = _scored(state, last, events)
            loss, cards = loss + more, cards + counted
    winner = state.winner() if game.game.completion == "finished" else None
    return GameFigures(loss, cards, leak, asks, None if winner is None else winner == 0)


# ---------------------------------------------------------------- the MDEs


def bootstrap_se(sums: Sequence[float], counts: Sequence[int], seed: int = SEED) -> float:
    """The standard error of the pooled ratio sum(sums) / sum(counts), resampling games."""
    rng = random.Random(seed)
    n = len(sums)
    estimates = []
    for _ in range(RESAMPLES):
        picks = [rng.randrange(n) for _ in range(n)]
        total = sum(counts[i] for i in picks)
        if total:
            estimates.append(sum(sums[i] for i in picks) / total)
    return statistics.stdev(estimates)


def mde(se: float, pilot_games: int, games: int) -> float:
    """The effect detectable in ``games`` games, from an SE measured over ``pilot_games``."""
    return Z * se * math.sqrt(pilot_games / games)


def win_rate_mde(p: float, games: int) -> float:
    """The difference between two win rates, each over ``games`` finished games, detectable
    when both are near ``p``."""
    return Z * math.sqrt(2 * p * (1 - p) / games)


@dataclass(frozen=True, slots=True)
class Result:
    games: int
    loss: tuple[float, float] | None
    """RQ1 proxy: the pooled mean, bits per card, and its bootstrap SE."""
    leak: tuple[float, float] | None
    """RQ2 proxy: the pooled mean, bits per ask, and its bootstrap SE."""
    win: tuple[float, int] | None
    """RQ3: team 0's share of finished games, and how many finished."""


def result(per_game: Sequence[GameFigures]) -> Result:
    def pooled(sums: list[float], counts: list[int]) -> tuple[float, float] | None:
        if len(sums) < 2 or not sum(counts):
            return None
        return sum(sums) / sum(counts), bootstrap_se(sums, counts)

    loss = pooled([g.loss_bits for g in per_game], [g.cards for g in per_game])
    leak = pooled([g.leak_bits for g in per_game], [g.asks for g in per_game])
    won = [g.team_0_won for g in per_game if g.team_0_won is not None]
    return Result(len(per_game), loss, leak, (sum(won) / len(won), len(won)) if won else None)


def read(conn: Connection, since: date | None) -> list[GameFigures]:
    """Every corpus game's proxies, of the games started on or after ``since`` (Eastern)."""
    games = chosen(conn, since)
    return [figures(read_corpus_record(r)) for r in records(conn, Summary(), only=games)]


def report(r: Result, since: date | None) -> list[str]:
    when = f"games started from {since.day} {since:%B %Y}" if since else "all games"
    lines = [f"Fish MDEs from the pilot: {r.games} corpus games, {when} (Eastern)", ""]
    finished = r.win[1] if r.win else 0
    if finished < FEW:
        lines += [f"Only {finished} finished games: too few for these to mean much.", ""]
    head = " | ".join(f"MDE at {n:,} games" for n in GAMES)
    lines += [
        f"| Primary metric | Proxy | Pilot value (SE) | {head} |",
        "|---|---|---|" + "---|" * len(GAMES),
    ]

    def row(metric: str, proxy: str, unit: str, value: tuple[float, float] | None) -> str:
        if value is None:
            return f"| {metric} | {proxy} | none | " + " | ".join("-" for _ in GAMES) + " |"
        mean, se = value
        mdes = " | ".join(f"{mde(se, r.games, n):.4f} {unit}" for n in GAMES)
        return f"| {metric} | {proxy} | {mean:.4f} ({se:.4f}) | {mdes} |"

    lines.append(row("RQ1 information gain", "Layer 1 log loss", "bits/card", r.loss))
    lines.append(row("RQ2 mean leakage", "hand-count policy, asks", "bits/ask", r.leak))
    if r.win is None:
        lines.append(
            "| RQ3 cross-play gap | win rate | none | " + " | ".join("-" for _ in GAMES) + " |"
        )
    else:
        p, n = r.win
        mdes = " | ".join(f"{win_rate_mde(p, g):.3f}" for g in GAMES)
        lines.append(f"| RQ3 cross-play gap | win rate, team 0 | {p:.3f} ({n} finished) | {mdes} |")
    lines += [
        "",
        f"Two-sided 5%, 80% power (z sum {Z:.3f}); game-level bootstrap, {RESAMPLES:,} "
        f"resamples, seed {SEED}. RQ3: two arms of that many finished games each.",
    ]
    return lines


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m fish_server.mde",
        description="Minimum detectable effects of the primary metrics, from the pilot.",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="only games started on or after this day, Eastern (YYYY-MM-DD)",
    )
    args = parser.parse_args(argv)
    engine = engine or create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            per_game = read(conn, args.since)
    finally:
        engine.dispose()
    print("\n".join(report(result(per_game), args.since)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
