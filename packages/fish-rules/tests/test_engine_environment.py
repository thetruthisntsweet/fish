"""Tests for the rules the engine owes the environment beyond single actions: asks resolved
automatically (R.2.4), no timers (R.8.6), and every agent asked in every window (R.8.9). The
rules only the website or client can show are owed by T3.1, T3.4 and T3.5; OWED in
scripts/check_rule_citations.py lists them."""

import ast
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

import fish_rules
from fish_rules.cards import SEATS
from fish_rules.engine import acting_seats, apply
from fish_rules.events import (
    AskEvent,
    AssignTimeout,
    ChoiceTimeout,
    CloseWindow,
    Declare,
    OpenWindow,
    Pass,
)
from fish_rules.playout import random_game
from fish_rules.state import Phase, new_game

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 10)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games are slower than single steps: a tenth of the profile's examples."""

CLOCKS = frozenset({"time", "datetime", "asyncio", "threading", "sched", "signal", "random"})
"""Standard modules that read a clock or keep time, or give unseeded randomness."""


# ---------------------------------------------------------------- R.2.4


@settings(max_examples=GAMES)
@given(U64, U64)
def test_r2_4_every_ask_is_resolved_from_the_hands(game_seed: int, policy_seed: int) -> None:
    """R.2.4: the engine answers every ask itself. Success is exactly whether the target held
    the card, which then moves; no player can answer falsely or decline to answer."""
    state = new_game(game_seed)
    asks = 0
    for action in random_game(game_seed, policy_seed):
        before = state
        state, records = apply(state, action)
        for record in records:
            if isinstance(record, AskEvent):
                asks += 1
                held = record.card in before.hands[record.target]
                assert record.success is held
                assert (record.card in state.hands[record.asker]) is held
                assert record.card not in state.hands[record.target]
    assert asks > 0 or state.phase is Phase.OVER


# ---------------------------------------------------------------- R.8.6


def test_r8_6_the_rules_engine_never_reads_a_clock() -> None:
    """R.8.6: the environment has no timers. No fish_rules module imports a clock, a timer or
    unseeded randomness, so nothing in a game can depend on time."""
    package = Path(fish_rules.__file__).parent
    sources = sorted(package.glob("*.py"))
    assert sources
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in CLOCKS, f"{path.name} imports {name}"


@settings(max_examples=GAMES)
@given(U64, U64)
def test_r8_6_environment_games_never_time_out(game_seed: int, policy_seed: int) -> None:
    """R.8.6: with no timers, an environment game never applies the website's timeout actions;
    every assignment and after-call choice is made by the agents."""
    actions = random_game(game_seed, policy_seed)
    assert not any(isinstance(a, AssignTimeout | ChoiceTimeout) for a in actions)


# ---------------------------------------------------------------- R.8.9


def test_r8_9_every_seat_is_asked_in_a_new_window() -> None:
    """R.8.9: when a window opens, all six seats are asked to declare or pass."""
    state, _ = apply(new_game(5), OpenWindow())
    assert acting_seats(state) == SEATS


@settings(max_examples=GAMES)
@given(U64, U64)
def test_r8_9_every_agent_responds_in_every_window(game_seed: int, policy_seed: int) -> None:
    """R.8.9: in environment games every window closes only after each of the six seats has
    declared or passed exactly once in it."""
    responders: list[int] | None = None
    windows = 0
    for action in random_game(game_seed, policy_seed):
        match action:
            case OpenWindow():
                assert responders is None
                responders = []
            case Declare(seat=seat) | Pass(seat=seat):
                assert responders is not None
                responders.append(seat)
            case CloseWindow():
                assert responders is not None
                assert sorted(responders) == list(SEATS)
                responders = None
                windows += 1
            case _:
                assert responders is None
    assert responders is None
    assert windows > 0
