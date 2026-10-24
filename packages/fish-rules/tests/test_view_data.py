"""Tests for the view as data (fish-view-v1): the frozen layout, checked against vectors from
the golden games, and plain JSON for every view of random games."""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import SEATS
from fish_rules.codec import action_from_data
from fish_rules.engine import apply, replay
from fish_rules.events import (
    AskEvent,
    CallEvent,
    ChoiceEvent,
    Declare,
    Event,
    OpenWindow,
)
from fish_rules.playout import random_game
from fish_rules.state import CallSource, State, new_game
from fish_rules.view import VIEW_ENCODING, event_to_data, latest_event, project, view_to_data

TESTS = Path(__file__).parent
VECTORS: dict[str, Any] = json.loads(
    (TESTS / "vectors" / "view_v1.json").read_text(encoding="utf-8")
)
U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 10)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games are slower than single steps: a tenth of the profile's examples."""

KEYS = {
    "encoding", "seat", "hand", "hand_sizes", "scored_by", "phase", "current", "call",
    "choice", "window", "last_event", "outcome", "winner", "legal",
}  # fmt: skip


def golden_state(game: str, step: int) -> tuple[State, Event | None]:
    """The state of golden game ``game`` after ``step`` actions, and its most recent event."""
    data: dict[str, Any] = json.loads((TESTS / "golden" / f"{game}.json").read_text("utf-8"))
    seed = int(data["seed"])
    actions = [action_from_data(item) for item in data["actions"][:step]]
    state, last = new_game(seed), None
    for after, records in replay(seed, actions):
        state, last = after, latest_event(records, last)
    return state, last


def plain(value: object) -> bool:
    """Whether ``value`` is JSON data made only of dicts with string keys, lists, strings,
    ints, bools and None."""
    if value is None or isinstance(value, str | int):
        return True
    if isinstance(value, list):
        items: list[object] = value  # pyright: ignore[reportUnknownVariableType]
        return all(plain(item) for item in items)
    if isinstance(value, dict):
        pairs: dict[object, object] = value  # pyright: ignore[reportUnknownVariableType]
        return all(isinstance(key, str) and plain(item) for key, item in pairs.items())
    return False


# ---------------------------------------------------------------- the frozen layout


def test_vectors_header() -> None:
    assert VECTORS["encoding"] == VIEW_ENCODING == "fish-view-v1"
    assert len(VECTORS["cases"]) == 124


@pytest.mark.parametrize(
    "case",
    VECTORS["cases"],
    ids=lambda c: f"{c['game']}@{c['step']}/seat{c['seat']}",
)
def test_frozen_views(case: dict[str, Any]) -> None:
    """Every frozen view, from every phase and after every kind of event, is written exactly
    as recorded."""
    state, last = golden_state(case["game"], case["step"])
    assert view_to_data(project(state, case["seat"], last)) == case["view"]


def test_the_vectors_cover_every_phase_and_event() -> None:
    phases = {case["view"]["phase"] for case in VECTORS["cases"]}
    kinds: set[str | None] = {
        None if case["view"]["last_event"] is None else case["view"]["last_event"]["type"]
        for case in VECTORS["cases"]
    }
    assert phases == {"turn", "window", "assign", "choose", "vote", "runout", "over"}
    assert kinds == {None, "AskEvent", "CallEvent", "ChoiceEvent"}


# ---------------------------------------------------------------- the data itself


def test_r2_2_a_fresh_game_as_data() -> None:
    state = new_game(7)
    data = view_to_data(project(state, 2, None))
    assert set(data) == KEYS
    assert data["seat"] == 2
    assert data["hand"] == list(state.hands[2])
    assert data["hand_sizes"] == [9] * 6
    assert data["scored_by"] == [None] * 9
    assert (data["phase"], data["current"]) == ("turn", state.current)
    assert (data["call"], data["choice"], data["window"], data["last_event"]) == (None,) * 4
    assert (data["outcome"], data["winner"]) == (None, None)


def test_r4_3_an_open_window_shows_only_your_own_answer() -> None:
    state, _ = apply(new_game(7), OpenWindow())
    state, _ = apply(state, Declare(0, 4))
    assert view_to_data(project(state, 0, None))["window"] == {
        "own_declaration": 4,
        "responded": True,
    }
    assert view_to_data(project(state, 1, None))["window"] == {
        "own_declaration": None,
        "responded": False,
    }


def test_r2_3_events_as_data() -> None:
    """R.2.3: a call's data carries the true holder of each card."""
    ask = AskEvent(number=3, asker=1, target=4, card=17, success=True)
    call = CallEvent(
        number=4,
        caller=2,
        set_id=5,
        source=CallSource.WINDOW,
        assignment=(0, 0, 1, 1, 2, 2),
        holders=(0, 1, 1, 1, 2, 2),
        correct=False,
        scored_by=1,
    )
    timed_out = CallEvent(
        number=5,
        caller=3,
        set_id=6,
        source=CallSource.TURN,
        assignment=None,
        holders=(3, 3, 4, 4, 5, 5),
        correct=False,
        scored_by=0,
    )
    choice = ChoiceEvent(number=6, team=0, seat=1)
    assert event_to_data(ask) == {
        "type": "AskEvent", "number": 3, "asker": 1, "target": 4, "card": 17, "success": True,
    }  # fmt: skip
    assert event_to_data(call) == {
        "type": "CallEvent", "number": 4, "caller": 2, "set_id": 5, "source": "window",
        "assignment": [0, 0, 1, 1, 2, 2], "holders": [0, 1, 1, 1, 2, 2], "correct": False,
        "scored_by": 1,
    }  # fmt: skip
    assert event_to_data(timed_out)["assignment"] is None
    assert event_to_data(choice) == {"type": "ChoiceEvent", "number": 6, "team": 0, "seat": 1}


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_every_view_is_plain_json(game_seed: int, policy_seed: int) -> None:
    """Every view of every seat at every step is plain JSON that survives a round trip
    unchanged, has exactly the fish-view-v1 keys, and never mentions the seed."""
    last: Event | None = None
    for state, records in replay(game_seed, random_game(game_seed, policy_seed)):
        last = latest_event(records, last)
        for seat in SEATS:
            data = view_to_data(project(state, seat, last))
            assert set(data) == KEYS
            assert plain(data)
            text = json.dumps(data)
            assert json.loads(text) == data
            assert "seed" not in text
