"""Tests for fish_rules.view: what each seat is shown (R.2), phase by phase, from the golden
games, and how a wrong most-recent event is rejected."""

import json
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from fish_rules.action_index import legal_indices
from fish_rules.cards import SEATS, team_seats
from fish_rules.codec import action_from_data
from fish_rules.engine import apply, replay
from fish_rules.events import (
    AskEvent,
    CallEvent,
    ChoiceEvent,
    Declare,
    Event,
    OpenWindow,
    Pass,
    Vote,
    WindowOpened,
)
from fish_rules.state import Outcome, Phase, State, new_game
from fish_rules.view import PlayerView, PublicCall, PublicChoice, latest_event, project

GOLDEN = Path(__file__).parent / "golden"


def golden_steps(name: str) -> Iterator[tuple[State, Event | None]]:
    """Every state of a golden game, with the most recent event at that point."""
    game: dict[str, Any] = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    actions = [action_from_data(data) for data in game["actions"]]
    last: Event | None = None
    for state, records in replay(int(game["seed"]), actions):
        last = latest_event(records, last)
        yield state, last


def first(name: str, phase: Phase) -> tuple[State, Event | None]:
    return next((s, e) for s, e in golden_steps(name) if s.phase is phase)


# ---------------------------------------------------------------- what every view holds


def test_r2_1_r2_2_a_fresh_game() -> None:
    """R.2.1: a seat sees its own hand. R.2.2: every hand size and the score are public; there
    is no event yet."""
    state = new_game(7)
    for seat in SEATS:
        view = project(state, seat, None)
        assert view.seat == seat
        assert view.hand == state.hands[seat]
        assert view.hand_sizes == (9,) * 6
        assert view.scored_by == (None,) * 9
        assert (view.score(0), view.score(1)) == (0, 0)
        assert view.phase is Phase.TURN
        assert view.current == state.current
        assert view.last_event is None
        assert (view.call, view.choice, view.window_open, view.responded) == (
            None,
            None,
            False,
            False,
        )
        assert (view.outcome, view.winner) == (None, None)
        assert view.legal == legal_indices(state, seat)


def test_the_view_has_no_field_for_hidden_information() -> None:
    """R.2.1: no seed (it would reveal the deal), no other hands, no window priority, no
    pending votes or declarations of other seats."""
    names = {field.name for field in fields(PlayerView)}
    assert names == {
        "seat", "hand", "hand_sizes", "scored_by", "phase", "current", "call", "choice",
        "window_open", "own_declaration", "responded", "last_event", "outcome", "winner",
        "legal",
    }  # fmt: skip


@pytest.mark.parametrize(
    "name",
    ["call_on_turn", "caller_chooses", "discarded_declaration", "runout", "seed_tiebreak",
     "team_0_wins", "team_1_wins", "team_votes"],
)  # fmt: skip
def test_r2_2_every_view_of_every_golden_state(name: str) -> None:
    """R.2.2: at every step of every golden game, each seat sees its own hand, every hand
    size, the scored sets and the most recent event, and exactly its legal actions."""
    for state, last in golden_steps(name):
        for seat in SEATS:
            view = project(state, seat, last)
            assert view.hand == state.hands[seat]
            assert view.hand_sizes == tuple(len(hand) for hand in state.hands)
            assert view.scored_by == state.scored_by
            assert view.last_event == last
            assert view.legal == legal_indices(state, seat)


# ---------------------------------------------------------------- phase by phase


def test_r4_3_r8_3_a_window_shows_only_your_own_answer() -> None:
    """R.4.3, R.8.3: in an open window a seat sees that it is open and its own answer; who
    else declared, and which set, stay hidden."""
    opened, _ = apply(new_game(7), OpenWindow())
    declared, _ = apply(apply(opened, Declare(0, 4))[0], Pass(1))
    passed, _ = apply(apply(opened, Pass(0))[0], Pass(1))
    zero, one, two = (project(declared, seat, None) for seat in (0, 1, 2))
    assert all(view.window_open for view in (zero, one, two))
    assert (zero.own_declaration, zero.responded) == (4, True)
    assert (one.own_declaration, one.responded) == (None, True)
    assert (two.own_declaration, two.responded) == (None, False)
    for seat in SEATS[1:]:
        assert project(declared, seat, None) == project(passed, seat, None)


def test_r8_3_the_call_being_assigned_is_public() -> None:
    """R.8.3: during the assignment every seat sees the caller and the set."""
    state, last = first("discarded_declaration", Phase.ASSIGN)
    assert state.call is not None
    for seat in SEATS:
        view = project(state, seat, last)
        assert view.call == PublicCall(state.call.caller, state.call.set_id)
        assert not view.window_open


def test_r2_3_a_call_event_reveals_the_true_holders() -> None:
    """R.2.3: when a call resolves, every seat sees the true holder of each of its cards."""
    state, last = next((s, e) for s, e in golden_steps("call_on_turn") if isinstance(e, CallEvent))
    for seat in SEATS:
        event = project(state, seat, last).last_event
        assert isinstance(event, CallEvent)
        assert len(event.holders) == 6


def test_r5_2_the_caller_chooses() -> None:
    state, last = first("caller_chooses", Phase.CHOOSE)
    assert state.choice is not None
    for seat in SEATS:
        choice = project(state, seat, last).choice
        assert choice is not None
        assert choice.chooser == state.choice.chooser is not None
        assert choice.candidates == state.choice.candidates
        assert choice.own_vote is None


def test_r5_2_only_your_own_vote_is_shown() -> None:
    """R.5.2: in a team vote each member sees its own vote and no one else's; the other team
    sees no votes."""
    state, last = first("team_votes", Phase.VOTE)
    assert state.choice is not None
    team = state.choice.team
    voter = team_seats(team)[0]
    chosen = state.choice.candidates[0]
    after, _ = apply(state, Vote(voter, chosen))
    assert after.phase is Phase.VOTE
    assert project(after, voter, last).choice == PublicChoice(
        team, state.choice.candidates, None, chosen
    )
    for seat in SEATS:
        if seat == voter:
            continue
        before_view = project(state, seat, last)
        after_view = project(after, seat, last)
        assert after_view.choice is not None
        assert after_view.choice.own_vote is None
        assert after_view == before_view


def test_r7_1_the_winner_is_shown_at_the_end() -> None:
    *_, (state, last) = golden_steps("team_1_wins")
    for seat in SEATS:
        view = project(state, seat, last)
        assert (view.outcome, view.winner) == (Outcome.FINISHED, 1)
        assert view.legal == ()


# ---------------------------------------------------------------- the most recent event


def test_r2_2_latest_event_keeps_only_the_most_recent() -> None:
    ask = AskEvent(number=0, asker=0, target=3, card=1, success=False)
    choice = ChoiceEvent(number=1, team=0, seat=2)
    assert latest_event([], None) is None
    assert latest_event([WindowOpened(index=0)], ask) is ask
    assert latest_event([ask, WindowOpened(index=1), choice], None) is choice


def test_the_most_recent_event_is_required_once_there_is_one() -> None:
    *_, (state, last) = (step for step in golden_steps("call_on_turn") if step[1] is not None)
    assert last is not None
    with pytest.raises(ValueError, match="pass the most recent"):
        project(state, 0, None)


def test_a_stale_event_is_rejected() -> None:
    steps = [step for step in golden_steps("call_on_turn") if step[1] is not None]
    (_, early), (state, late) = steps[0], steps[-1]
    assert early is not None
    assert late is not None
    assert early.number < late.number
    with pytest.raises(ValueError, match="not the most recent"):
        project(state, 0, early)


def test_an_event_before_the_first_is_rejected() -> None:
    with pytest.raises(ValueError, match="not the most recent"):
        project(new_game(1), 0, AskEvent(number=0, asker=0, target=3, card=1, success=True))


def test_project_checks_the_seat() -> None:
    with pytest.raises(ValueError, match="seat must be in"):
        project(new_game(1), 6, None)
