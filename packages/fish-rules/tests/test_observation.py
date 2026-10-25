"""Tests for fish_rules.observation: the frozen fish-obs-v1 layout, block by block, against
views from the golden games and random games."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.action_index import opponents, teammates
from fish_rules.cards import SEATS, team_of
from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.observation import (
    HAND_SIZE_VALUES,
    OBS_ENCODING,
    OBS_LAYOUT,
    OBS_SIZE,
    OFFSETS,
    PHASES,
    encode,
    seat_slots,
)
from fish_rules.playout import random_game
from fish_rules.state import CallSource, Outcome, Phase, State, new_game
from fish_rules.view import PlayerView, latest_event, project

TESTS = Path(__file__).parent
VECTORS: dict[str, Any] = json.loads((TESTS / "vectors" / "obs_v1.json").read_text("utf-8"))
U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Every seat at every step of whole games is costly: a fortieth of the profile's examples
(10 in dev, 25 in CI, 1,250 nightly)."""

ONE_HOT = (
    "me", "phase", "current", "call_caller", "call_set", "choice_team", "choice_chooser",
    "own_vote", "own_declaration", "event", "ask_asker", "ask_target", "ask_card",
    "call_event_caller", "call_event_set", "call_event_source", "call_event_scored_by",
    "choice_event_team", "choice_event_seat", "outcome", "winner",
)  # fmt: skip
"""Blocks with at most one bit set."""


def block(bits: bytes, name: str) -> list[int]:
    """The indices set within block ``name``."""
    width = dict(OBS_LAYOUT)[name]
    start = OFFSETS[name]
    return [i for i in range(width) if bits[start + i]]


def golden_state(game: str, step: int) -> tuple[State, Event | None]:
    data: dict[str, Any] = json.loads((TESTS / "golden" / f"{game}.json").read_text("utf-8"))
    seed = int(data["seed"])
    actions = [action_from_data(item) for item in data["actions"][:step]]
    state, last = new_game(seed), None
    for after, records in replay(seed, actions):
        state, last = after, latest_event(records, last)
    return state, last


def fresh_view(seat: int = 1) -> PlayerView:
    return project(new_game(7), seat, None)


# ---------------------------------------------------------------- the frozen layout


def test_layout() -> None:
    names = [name for name, _ in OBS_LAYOUT]
    assert len(names) == len(set(names))
    assert OBS_ENCODING == "fish-obs-v1"
    assert OBS_SIZE == 648
    assert (OFFSETS["hand"], OFFSETS["hand_sizes"], OFFSETS["phase"]) == (0, 57, 414)
    assert OFFSETS["winner"] + 2 == OBS_SIZE


def test_vectors_header() -> None:
    assert VECTORS["encoding"] == OBS_ENCODING
    assert VECTORS["size"] == OBS_SIZE
    assert len(VECTORS["cases"]) == 124


@pytest.mark.parametrize(
    "case", VECTORS["cases"], ids=lambda c: f"{c['game']}@{c['step']}/seat{c['seat']}"
)
def test_frozen_observations(case: dict[str, Any]) -> None:
    state, last = golden_state(case["game"], case["step"])
    bits = encode(project(state, case["seat"], last))
    assert [i for i, bit in enumerate(bits) if bit] == case["ones"]


# ---------------------------------------------------------------- seats relative to the observer


def test_seat_slots_match_the_action_layout() -> None:
    """Slots 0-2 are the action layout's teammate indices, slots 3-5 its opponent indices."""
    for seat in SEATS:
        assert seat_slots(seat) == (*teammates(seat), *opponents(seat))
        assert sorted(seat_slots(seat)) == list(SEATS)


def test_r2_1_r2_2_a_fresh_game() -> None:
    """R.2.1: the seat's own hand. R.2.2: every hand size and every set in play."""
    state = new_game(7)
    for seat in SEATS:
        bits = encode(project(state, seat, None))
        assert len(bits) == OBS_SIZE
        assert set(bits) <= {0, 1}
        assert block(bits, "hand") == list(state.hands[seat])
        assert block(bits, "me") == [teammates(seat).index(seat)]
        assert block(bits, "hand_sizes") == [s * HAND_SIZE_VALUES + 9 for s in range(6)]
        assert block(bits, "sets") == [s * 3 for s in range(9)]
        assert block(bits, "phase") == [PHASES.index(Phase.TURN)]
        assert state.current is not None
        assert block(bits, "current") == [seat_slots(seat).index(state.current)]
        for name in ("call_caller", "choice_team", "own_declaration", "responded", "event"):
            assert block(bits, name) == []


# ---------------------------------------------------------------- events


def test_r3_3_an_ask() -> None:
    view = replace(fresh_view(1), last_event=AskEvent(0, asker=1, target=5, card=40, success=True))
    bits = encode(view)
    assert block(bits, "event") == [0]
    assert block(bits, "ask_asker") == [1]  # seat 1 is teammate slot 1
    assert block(bits, "ask_target") == [5]  # seat 5 is opponent slot 2
    assert block(bits, "ask_card") == [40]
    assert block(bits, "ask_success") == [0]


def test_r2_3_a_call_reveals_the_true_holders() -> None:
    call = CallEvent(
        number=0,
        caller=4,
        set_id=3,
        source=CallSource.TURN,
        assignment=(3, 3, 4, 4, 5, 5),
        holders=(3, 4, 4, 4, 5, 2),
        correct=False,
        scored_by=0,
    )
    bits = encode(replace(fresh_view(0), last_event=call))
    assert block(bits, "event") == [1]
    assert block(bits, "call_event_caller") == [4]
    assert block(bits, "call_event_set") == [3]
    assert block(bits, "call_event_source") == [1]
    assert block(bits, "call_event_assignment") == [3, 9, 16, 22, 29, 35]
    assert block(bits, "call_event_holders") == [3, 10, 16, 22, 29, 32]
    assert block(bits, "call_event_correct") == []
    assert block(bits, "call_event_scored_by") == [0]  # scored for the observer's team
    assert block(bits, "call_event_timed_out") == []


def test_r4_3_a_timed_out_call_has_no_assignment() -> None:
    call = CallEvent(0, 2, 1, CallSource.WINDOW, None, (0, 0, 1, 1, 2, 2), False, 1)
    bits = encode(replace(fresh_view(3), last_event=call))
    assert block(bits, "call_event_assignment") == []
    assert block(bits, "call_event_timed_out") == [0]
    assert block(bits, "call_event_scored_by") == [0]  # team 1 is the observer's


def test_r5_2_a_choice() -> None:
    bits = encode(replace(fresh_view(2), last_event=ChoiceEvent(0, team=1, seat=3)))
    assert block(bits, "event") == [2]
    assert block(bits, "choice_event_team") == [1]
    assert block(bits, "choice_event_seat") == [3]


def test_r7_1_the_end_from_both_sides() -> None:
    view = replace(fresh_view(0), phase=Phase.OVER, current=None)
    won = encode(replace(view, outcome=Outcome.FINISHED, winner=team_of(0)))
    lost = encode(replace(view, outcome=Outcome.FINISHED, winner=1 - team_of(0)))
    unfinished = encode(replace(view, outcome=Outcome.UNFINISHED))
    assert (block(won, "outcome"), block(won, "winner")) == ([0], [0])
    assert (block(lost, "outcome"), block(lost, "winner")) == ([0], [1])
    assert (block(unfinished, "outcome"), block(unfinished, "winner")) == ([1], [])
    assert block(won, "current") == []


# ---------------------------------------------------------------- every view of random games


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_every_observation_matches_its_view(game_seed: int, policy_seed: int) -> None:
    """At every step of random games, for every seat: one-hot blocks have at most one bit,
    and the blocks agree with the view they encode."""
    last: Event | None = None
    for state, records in replay(game_seed, random_game(game_seed, policy_seed)):
        last = latest_event(records, last)
        for seat in SEATS:
            view = project(state, seat, last)
            bits = encode(view)
            slots = seat_slots(seat)
            for name in ONE_HOT:
                assert len(block(bits, name)) <= 1, name
            assert block(bits, "hand") == list(view.hand)
            assert block(bits, "hand_sizes") == [
                slots.index(s) * HAND_SIZE_VALUES + view.hand_sizes[s]
                for s in sorted(SEATS, key=slots.index)
            ]
            assert len(block(bits, "sets")) == 9
            assert block(bits, "phase") == [PHASES.index(view.phase)]
            assert block(bits, "responded") == ([0] if view.responded else [])
            if view.choice is not None:
                assert block(bits, "choice_candidates") == sorted(
                    slots.index(s) for s in view.choice.candidates
                )
            if isinstance(view.last_event, CallEvent):
                assert len(block(bits, "call_event_holders")) == 6
