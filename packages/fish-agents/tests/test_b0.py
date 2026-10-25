"""Tests for B0 (b0-v1): it plays only legal actions, chooses uniformly, declares in a window
one time in 100, and plays the frozen games."""

from collections import Counter

import pytest

from fish_agents.b0 import B0, B0_VERSION, DECLARE_ODDS
from fish_agents.play import play_game
from fish_rules.action_index import CALL_BASE, DECLARE_BASE, PASS_INDEX
from fish_rules.codec import action_from_data
from fish_rules.engine import apply, replay
from fish_rules.events import AskEvent, CallEvent, OpenWindow
from fish_rules.record import replay_record
from fish_rules.rng import SplitMix64
from fish_rules.state import Outcome, new_game, state_hash
from fish_rules.view import PlayerView, project

DRAWS = 20_000

FROZEN = (
    (0, 423, "7927f7caa0f4f5a2f6083953f8c820a67195ff5973fe106304681c8c9ba83d93"),
    (1, 504, "5e058ee267728480c56066ce5d77c74c5f527cf14457317820296dd2e0e84e2d"),
    (2, 628, "828a1628d9c8b7cc88e606eeb2e72376c78593d79d91f15b2b10f097d67e9bbf"),
    (3, 346, "cc8432724eec996035912dc951a879d211242ff2b7e4cfbbfa9e2291050314be"),
    (4, 309, "1b6615b8a18909835244b743e59657d8f3e81026930c8e7cae207ef4e85cfbc4"),
)
"""b0-v1 games: seed, number of actions, final state hash. If these change, B0 changed."""


def window_view() -> PlayerView:
    state, _ = apply(new_game(7), OpenWindow())
    return project(state, 2, None)


def turn_view() -> PlayerView:
    state = new_game(7)
    assert state.current is not None
    return project(state, state.current, None)


def test_version() -> None:
    assert (B0_VERSION, DECLARE_ODDS) == ("b0-v1", 100)


@pytest.mark.parametrize(("seed", "actions", "final"), FROZEN)
def test_frozen_games(seed: int, actions: int, final: str) -> None:
    record = play_game([B0()] * 6, seed)
    assert len(record["actions"]) == actions  # pyright: ignore[reportArgumentType]
    assert state_hash(replay_record(record)) == final


def test_a_window_answer_is_a_pass_except_one_time_in_100() -> None:
    """Over 20,000 window answers, about 200 are declarations (within 4 standard deviations
    of 1 in 100), spread over all nine sets, and every other answer is a pass."""
    view = window_view()
    rng = SplitMix64(1)
    choices = Counter(B0().act(view, rng) for _ in range(DRAWS))
    declared = DRAWS - choices[PASS_INDEX]
    expected = DRAWS / DECLARE_ODDS
    assert abs(declared - expected) < 4 * (expected * (1 - 1 / DECLARE_ODDS)) ** 0.5
    assert set(choices) == {PASS_INDEX, *range(DECLARE_BASE, PASS_INDEX)}


def test_a_turn_choice_is_uniform_over_legal_actions() -> None:
    """On a turn every legal ask and call is chosen, each about equally often."""
    view = turn_view()
    rng = SplitMix64(2)
    choices = Counter(B0().act(view, rng) for _ in range(DRAWS))
    assert set(choices) == set(view.legal)
    expected = DRAWS / len(view.legal)
    assert all(abs(count - expected) < 5 * expected**0.5 for count in choices.values())
    assert any(index >= CALL_BASE for index in choices)


def test_only_legal_actions_and_a_game_with_asks() -> None:
    """B0 plays whole games without an illegal action (the environment would raise), and its
    games include asks and calls."""
    for seed in range(10):
        record = play_game([B0()] * 6, 100 + seed)
        state = replay_record(record)
        assert state.outcome is Outcome.FINISHED
        actions = [action_from_data(data) for data in record["actions"]]  # pyright: ignore[reportUnknownVariableType, reportGeneralTypeIssues]
        records = [r for _, step in replay(int(str(record["seed"])), actions) for r in step]
        assert any(isinstance(r, AskEvent) for r in records)
        assert any(isinstance(r, CallEvent) for r in records)


def test_b0_is_deterministic() -> None:
    assert play_game([B0()] * 6, 55) == play_game([B0() for _ in range(6)], 55)
