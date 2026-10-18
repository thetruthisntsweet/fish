"""Tests for running out (R.6.2): when one team holds no cards, the other calls the remaining
sets one at a time, each caller chosen by R.8.1 priority, with no after-call choice."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from fish_rules.cards import CARDS, NUM_SEATS, Card, Seat, set_cards, set_of, team_of
from fish_rules.engine import IllegalActionError, apply
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    Assign,
    Call,
    CallEvent,
    ChoiceEvent,
    CloseWindow,
    Declare,
    GameOver,
    OpenWindow,
    Record,
    RunoutCallerSelected,
)
from fish_rules.priority import runout_caller
from fish_rules.state import (
    MAX_ASKS,
    CallSource,
    Outcome,
    Phase,
    State,
    check_consistency,
    new_game,
)

SEED = 21


# ---------------------------------------------------------------- helpers


def arranged(where: Callable[[Card], Seat], *, seed: int = SEED, current: Seat = 0) -> State:
    """A turn for ``current`` in a game whose cards are held as ``where`` says."""
    hands = tuple(tuple(card for card in CARDS if where(card) == seat) for seat in range(NUM_SEATS))
    state = replace(new_game(seed), hands=hands, current=current)
    check_consistency(state)
    return state


def play(state: State, *actions: Action) -> tuple[State, tuple[Record, ...]]:
    records: tuple[Record, ...] = ()
    for action in actions:
        state, step = apply(state, action)
        records += step
    return state, records


def truth(state: State, set_id: int) -> tuple[Seat, ...]:
    holders = tuple(state.holder(card) for card in set_cards(set_id))
    return tuple(holder for holder in holders if holder is not None)


def team_one_holds_only_set_4(card: Card) -> Seat:
    """Set 4 is split between seats 3 and 4; every other card goes round seats 0, 1 and 2."""
    if set_of(card) == 4:
        return 3 + card % 2
    return card % 3


def runout_after_team_one_calls_out() -> tuple[State, tuple[Record, ...]]:
    """Seat 3 calls set 4 correctly; team 1 then holds no cards, so team 0 runs out."""
    state = arranged(team_one_holds_only_set_4)
    state, _ = play(state, OpenWindow(), Declare(3, 4), CloseWindow())
    return play(state, Assign(3, truth(state, 4)))


# ---------------------------------------------------------------- R.6.2 when run-out starts


def test_r6_2_runout_starts_when_an_ask_empties_a_team() -> None:
    """R.6.2: if one team holds no cards, asking ends. A successful ask can take the last card
    of the other team; the team holding cards then calls, chosen by R.8.1 priority, and the
    selection counts as a declaration window."""
    state = arranged(lambda card: 3 if card == 0 else 0)
    state, records = apply(state, Ask(0, 3, 0))
    selected = runout_caller(SEED, 0, 0)
    assert records == (
        AskEvent(number=0, asker=0, target=3, card=0, success=True),
        RunoutCallerSelected(window=0, seat=selected),
    )
    assert state.phase is Phase.RUNOUT
    assert state.current == selected
    assert state.windows_opened == 1
    check_consistency(state)


def test_r8_2_the_ask_limit_comes_before_runout() -> None:
    """R.8.2: a game that reaches 1,000 asks ends as unfinished, even if the last ask also
    leaves a team without cards."""
    state = replace(arranged(lambda card: 3 if card == 0 else 0), asks=MAX_ASKS - 1)
    state, records = apply(state, Ask(0, 3, 0))
    assert state.phase is Phase.OVER
    assert state.outcome is Outcome.UNFINISHED
    assert records[-1] == GameOver(outcome=Outcome.UNFINISHED, winner=None)


def test_r6_2_r5_1_runout_starts_after_a_call_with_no_choice() -> None:
    """R.6.2: a call that leaves one team without cards starts run-out. R.5.1: under R.6.2 no
    after-call choice is made."""
    state, records = runout_after_team_one_calls_out()
    assert isinstance(records[-2], CallEvent)
    assert records[-2].correct
    assert records[-1] == RunoutCallerSelected(window=1, seat=runout_caller(SEED, 1, 0))
    assert not any(isinstance(record, ChoiceEvent) for record in records)
    assert state.phase is Phase.RUNOUT
    assert state.choice is None
    check_consistency(state)


def test_r6_2_r9_incorrect_call_that_empties_the_scoring_team() -> None:
    """R.9: every call is followed by a choice among players holding cards, except under R.6.2.
    An incorrect call can score a set for a team that then holds no cards; it cannot choose,
    and the other team runs out."""
    state = arranged(team_one_holds_only_set_4)
    state, records = play(state, OpenWindow(), Declare(0, 4), CloseWindow(), Assign(0, (0,) * 6))
    call = records[-2]
    assert isinstance(call, CallEvent)
    assert not call.correct
    assert call.scored_by == 1
    assert records[-1] == RunoutCallerSelected(window=1, seat=runout_caller(SEED, 1, 0))
    assert state.phase is Phase.RUNOUT


# ---------------------------------------------------------------- R.6.2 who may act


def test_r6_2_only_the_selected_caller_may_call() -> None:
    """R.6.2: only the selected caller may call; players on the team without cards may no
    longer call. Asking has ended and no window opens."""
    state, _ = runout_after_team_one_calls_out()
    caller = state.current
    assert caller is not None
    for seat in range(NUM_SEATS):
        if seat != caller:
            with pytest.raises(IllegalActionError, match="only the selected caller"):
                apply(state, Call(seat, 0))
    with pytest.raises(IllegalActionError, match="no one may ask"):
        apply(state, Ask(caller, 3, 0))
    with pytest.raises(IllegalActionError, match="cannot open"):
        apply(state, OpenWindow())
    with pytest.raises(IllegalActionError, match="cannot declare"):
        apply(state, Declare(caller, 0))
    with pytest.raises(IllegalActionError, match="already been scored"):
        apply(state, Call(caller, 4))


def test_r6_2_the_selected_caller_names_the_set_then_assigns() -> None:
    """R.6.2: the caller names the set and has 30 seconds (untimed here) to assign its six
    cards."""
    state, _ = runout_after_team_one_calls_out()
    caller = state.current
    assert caller is not None
    state, records = apply(state, Call(caller, 0))
    assert records == ()
    assert state.phase is Phase.ASSIGN
    assert state.call is not None
    assert state.call.source is CallSource.RUNOUT
    check_consistency(state)


def test_r6_1_the_selected_caller_may_hold_no_cards() -> None:
    """R.6.1: a player with no cards may still call. R.6.2: the caller is the first member of
    the team in priority order, whether or not they hold cards."""
    cardless = runout_caller(SEED, 1, 0)

    def where(card: Card) -> Seat:
        seat = team_one_holds_only_set_4(card)
        return (seat + 1) % 3 if seat == cardless else seat

    state = arranged(where)
    assert state.hands[cardless] == ()
    state, _ = play(state, OpenWindow(), Declare(3, 4), CloseWindow())
    state, _ = play(state, Assign(3, truth(state, 4)))
    assert state.current == cardless
    state, _ = play(state, Call(cardless, 0))
    state, records = play(state, Assign(cardless, truth(state, 0)))
    first = records[0]
    assert isinstance(first, CallEvent)
    assert first.correct


# ---------------------------------------------------------------- R.6.2 to the end of the game


def test_r6_2_r7_runout_continues_set_by_set_until_the_game_ends() -> None:
    """R.6.2: the team holding cards calls the remaining sets one at a time until R.7 ends the
    game. Before each call the caller is chosen afresh by R.8.1, and each selection counts as a
    window, so window indices keep counting up."""
    state, records = runout_after_team_one_calls_out()
    index = 1
    calls = 0
    while state.phase is Phase.RUNOUT:
        caller = state.current
        assert caller is not None
        assert caller == runout_caller(SEED, index, 0)
        set_id = state.sets_in_play()[0]
        state, records = play(state, Call(caller, set_id), Assign(caller, truth(state, set_id)))
        calls += 1
        call = records[0]
        assert isinstance(call, CallEvent)
        assert (call.source, call.correct, call.scored_by) == (CallSource.RUNOUT, True, 0)
        assert not any(isinstance(record, ChoiceEvent) for record in records)
        check_consistency(state)
        index += 1
        if state.phase is Phase.RUNOUT:
            assert state.current is not None
            assert records[1] == RunoutCallerSelected(window=index, seat=state.current)
    assert calls == 5
    assert state.outcome is Outcome.FINISHED
    assert records[-1] == GameOver(outcome=Outcome.FINISHED, winner=0)
    assert state.windows_opened == index


def test_r6_2_r4_4_incorrect_runout_calls_score_for_the_team_without_cards() -> None:
    """R.4.4 still applies during run-out: an incorrect call scores the set for the other team,
    which can win the game without holding a card."""
    state, records = runout_after_team_one_calls_out()
    while state.phase is Phase.RUNOUT:
        caller = state.current
        assert caller is not None
        set_id = state.sets_in_play()[0]
        state, records = play(state, Call(caller, set_id), Assign(caller, (caller,) * 6))
        call = records[0]
        assert isinstance(call, CallEvent)
        assert not call.correct
        assert team_of(caller) == 0
    assert (state.score(0), state.score(1)) == (0, 5)
    assert records[-1] == GameOver(outcome=Outcome.FINISHED, winner=1)
