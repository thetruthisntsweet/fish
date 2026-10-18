"""Tests for fish_rules.action_index: the frozen layout of seat actions as integers, and the
legal indices and mask built from the engine's legal actions."""

import json
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.action_index import (
    ACTION_INDEX_ENCODING,
    ASK_BASE,
    ASSIGN_BASE,
    CALL_BASE,
    DECLARE_BASE,
    NOMINATE_BASE,
    NUM_ACTIONS,
    PASS_INDEX,
    SeatAction,
    decode,
    encode,
    legal_indices,
    legal_mask,
    opponents,
    teammates,
)
from fish_rules.cards import SEATS, team_of
from fish_rules.codec import ACTION_ENCODING, action_from_data
from fish_rules.engine import acting_seats, apply, legal_actions
from fish_rules.events import (
    Action,
    Ask,
    Assign,
    AssignTimeout,
    Call,
    ChoiceTimeout,
    Choose,
    CloseWindow,
    Declare,
    OpenWindow,
    Pass,
    Vote,
)
from fish_rules.playout import random_game
from fish_rules.state import Phase, new_game

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "vectors" / "action_index_v1.json").read_text(encoding="utf-8")
)
U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 10)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games are slower than single steps: a tenth of the profile's examples."""

PHASES = (Phase.TURN, Phase.VOTE)
CONTROL: tuple[Action, ...] = (OpenWindow(), CloseWindow(), AssignTimeout(), ChoiceTimeout())


# ---------------------------------------------------------------- the frozen layout


def test_layout() -> None:
    assert ACTION_INDEX_ENCODING == "fish-action-index-v1"
    assert (ASK_BASE, CALL_BASE, DECLARE_BASE, PASS_INDEX) == (0, 162, 171, 180)
    assert (ASSIGN_BASE, NOMINATE_BASE, NUM_ACTIONS) == (181, 910, 913)


def test_vectors_header() -> None:
    assert VECTORS["encoding"] == ACTION_INDEX_ENCODING
    assert VECTORS["action_encoding"] == ACTION_ENCODING
    assert VECTORS["num_actions"] == NUM_ACTIONS
    assert sorted(VECTORS["seats"]) == ["1", "4"]


@pytest.mark.parametrize("seat", ["1", "4"])
def test_frozen_vectors(seat: str) -> None:
    """Every index for one seat of each team decodes to the frozen action and encodes back."""
    entries = VECTORS["seats"][seat]
    assert [index for index, _ in entries] == list(range(NUM_ACTIONS))
    for index, data in entries:
        action = action_from_data(data)
        assert decode(int(seat), index, Phase.CHOOSE) == action
        assert encode(action) == index


def test_relative_seats() -> None:
    """Opponent and teammate indices are the other team's and own team's seats, ascending."""
    for seat in SEATS:
        assert opponents(seat) == tuple(s for s in SEATS if team_of(s) != team_of(seat))
        assert teammates(seat) == tuple(s for s in SEATS if team_of(s) == team_of(seat))


# ---------------------------------------------------------------- encode and decode


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("phase", PHASES, ids=str)
def test_every_index_round_trips(seat: int, phase: Phase) -> None:
    actions = [decode(seat, index, phase) for index in range(NUM_ACTIONS)]
    assert [encode(action) for action in actions] == list(range(NUM_ACTIONS))
    assert len(set(actions)) == NUM_ACTIONS
    assert all(action.seat == seat for action in actions)


def test_r5_2_nomination_is_a_vote_only_in_the_vote() -> None:
    """R.5.2: the same index nominates a teammate, as the caller's choice or as a vote."""
    assert decode(4, NOMINATE_BASE + 2, Phase.VOTE) == Vote(4, 5)
    assert decode(4, NOMINATE_BASE + 2, Phase.CHOOSE) == Choose(4, 5)
    assert encode(Vote(4, 5)) == encode(Choose(4, 5)) == NOMINATE_BASE + 2


def test_r4_1_assignment_digits() -> None:
    """R.4.1: the set's first card is the most significant base-3 digit."""
    assert encode(Assign(0, (0, 0, 0, 0, 0, 0))) == ASSIGN_BASE
    assert encode(Assign(0, (0, 0, 0, 0, 0, 1))) == ASSIGN_BASE + 1
    assert encode(Assign(0, (1, 0, 0, 0, 0, 0))) == ASSIGN_BASE + 243
    assert encode(Assign(5, (5, 5, 5, 5, 5, 5))) == NOMINATE_BASE - 1


NO_INDEX: tuple[tuple[Action, str], ...] = (
    (Ask(0, 1, 7), "not an opponent"),  # R.3.2: a teammate is not an opponent
    (Assign(0, (0, 1, 2, 0, 1)), "six holders"),
    (Assign(0, (0, 1, 2, 0, 1, 3)), "not a teammate"),  # R.4.1: holders are teammates
    (Choose(3, 2), "not a teammate"),
    (Vote(3, 0), "not a teammate"),
    (Ask(0, 3, 54), "card must be in"),
    (Call(0, 9), "set must be in"),
    (Declare(6, 0), "seat must be in"),
    (Pass(-1), "seat must be in"),
    *((action, "control action") for action in CONTROL),
)


@pytest.mark.parametrize(("action", "match"), NO_INDEX, ids=[repr(a) for a, _ in NO_INDEX])
def test_actions_without_an_index_are_rejected(action: Action, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        encode(action)


@pytest.mark.parametrize("index", [-1, NUM_ACTIONS, True])
def test_indices_out_of_range_are_rejected(index: int) -> None:
    with pytest.raises(ValueError, match="range"):
        decode(0, index, Phase.TURN)


def test_decode_checks_the_seat() -> None:
    with pytest.raises(ValueError, match="seat must be in"):
        decode(6, 0, Phase.TURN)


# ---------------------------------------------------------------- legal indices and the mask


def test_r8_9_new_game_window() -> None:
    """R.8.9: in a fresh window every seat may pass or declare any of the nine sets."""
    state, _ = apply(new_game(3), OpenWindow())
    expected = (PASS_INDEX, *range(DECLARE_BASE, PASS_INDEX))
    for seat in SEATS:
        assert legal_indices(state, seat) == tuple(sorted(expected))


@settings(max_examples=GAMES, deadline=None)  # every seat at every step of a whole game
@given(U64, U64)
def test_legal_indices_are_exactly_the_legal_actions(game_seed: int, policy_seed: int) -> None:
    """At every step of random games, every seat's legal indices decode to exactly its legal
    actions, and the mask marks exactly those indices."""
    state = new_game(game_seed)
    phases: set[Phase] = set()
    for action in random_game(game_seed, policy_seed):
        phases.add(state.phase)
        acting = set(acting_seats(state))
        for seat in SEATS:
            indices = legal_indices(state, seat)
            assert list(indices) == sorted(set(indices))
            decoded: set[SeatAction] = {decode(seat, i, state.phase) for i in indices}
            assert decoded == set(legal_actions(state, seat))
            assert bool(indices) == (seat in acting)
            mask = legal_mask(state, seat)
            assert len(mask) == NUM_ACTIONS
            assert [i for i, bit in enumerate(mask) if bit] == list(indices)
            assert set(mask) <= {0, 1}
        state, _ = apply(state, action)
    assert {Phase.TURN, Phase.WINDOW, Phase.ASSIGN} <= phases
    assert legal_indices(state, 0) == ()


def test_assignment_mask_is_every_assignment_to_teammates() -> None:
    """R.4.1: during the assignment the caller may assign each card to any teammate: all 729."""
    state = new_game(11)
    state, _ = apply(state, OpenWindow())
    for seat in SEATS:
        state, _ = apply(state, Declare(seat, 0) if seat == 2 else Pass(seat))
    state, _ = apply(state, CloseWindow())
    assert state.phase is Phase.ASSIGN
    assert legal_indices(state, 2) == tuple(range(ASSIGN_BASE, NOMINATE_BASE))
    assert {decode(2, i, state.phase) for i in legal_indices(state, 2)} == {
        Assign(2, holders) for holders in product((0, 1, 2), repeat=6)
    }
