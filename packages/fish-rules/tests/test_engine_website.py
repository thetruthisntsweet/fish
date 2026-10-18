"""Tests for the rule outcomes of the website's timers and Call-press races (R.4.3, R.5.2,
R.8.7). The timers themselves run in the server (T3.1); the environment never uses these
actions (R.8.6)."""

from collections.abc import Callable
from dataclasses import replace

import pytest

from fish_rules.cards import CARDS, NUM_SEATS, Card, Seat, next_teammate, set_cards, set_of
from fish_rules.engine import IllegalActionError, apply, press_is_stale, tiebreak_seat
from fish_rules.events import (
    Action,
    AskEvent,
    Assign,
    AssignTimeout,
    CallEvent,
    ChoiceEvent,
    ChoiceTimeout,
    CloseWindow,
    Declare,
    GameOver,
    OpenWindow,
    Record,
    RunoutCallerSelected,
    SeedChose,
    Vote,
    VoteCast,
    WindowOpened,
)
from fish_rules.state import CallSource, Outcome, Phase, State, check_consistency, new_game

SEED = 31


# ---------------------------------------------------------------- helpers


def play(state: State, *actions: Action) -> tuple[State, tuple[Record, ...]]:
    records: tuple[Record, ...] = ()
    for action in actions:
        state, step = apply(state, action)
        records += step
    return state, records


def give(state: State, set_id: int, seats: tuple[Seat, ...]) -> State:
    cards = set_cards(set_id)
    hands = [tuple(card for card in hand if card not in cards) for hand in state.hands]
    for i, card in enumerate(cards):
        seat = seats[i % len(seats)]
        hands[seat] = tuple(sorted((*hands[seat], card)))
    return replace(state, hands=tuple(hands))


def empty_hand(state: State, seat: Seat) -> State:
    mate = next_teammate(seat)
    hands = list(state.hands)
    hands[mate] = tuple(sorted((*hands[mate], *hands[seat])))
    hands[seat] = ()
    return replace(state, hands=tuple(hands))


def truth(state: State, set_id: int) -> tuple[Seat, ...]:
    holders = tuple(state.holder(card) for card in set_cards(set_id))
    return tuple(holder for holder in holders if holder is not None)


def assigning(state: State, caller: Seat, set_id: int) -> State:
    """``caller`` has declared ``set_id`` alone in a window and must now assign."""
    state, _ = play(state, OpenWindow(), Declare(caller, set_id), CloseWindow())
    return state


def choosing(state: State | None = None) -> State:
    """Seat 1 called set 2 correctly and must now choose among team 0's card holders."""
    state = assigning(give(state or new_game(SEED), 2, (0, 1, 2)), 1, 2)
    state, _ = play(state, Assign(1, truth(state, 2)))
    assert state.phase is Phase.CHOOSE
    return state


def voting(state: State | None = None) -> State:
    """Seat 0 called set 2 incorrectly; team 1 now votes."""
    state = assigning(give(state or new_game(SEED), 2, (3, 4)), 0, 2)
    state, _ = play(state, Assign(0, (0,) * 6))
    assert state.phase is Phase.VOTE
    return state


# ---------------------------------------------------------------- R.4.3 the 30-second assignment


def test_r4_3_caller_who_runs_out_of_time_has_made_an_incorrect_call() -> None:
    """R.4.3: a caller who does not finish in 30 seconds has made an incorrect call. R.4.4: the
    set scores for the other team. R.4.5: its six cards leave play. R.2.3: the true holders are
    revealed. R.5.2: the other team then votes."""
    state = assigning(give(new_game(SEED), 5, (0, 1)), 0, 5)
    holders = truth(state, 5)
    number = state.events
    after, records = apply(state, AssignTimeout())
    assert records == (
        CallEvent(
            number=number,
            caller=0,
            set_id=5,
            source=CallSource.WINDOW,
            assignment=None,
            holders=holders,
            correct=False,
            scored_by=1,
        ),
    )
    assert after.scored_by[5] == 1
    assert all(after.holder(card) is None for card in set_cards(5))
    assert after.phase is Phase.VOTE
    check_consistency(after)


def test_r4_3_timeout_only_during_an_assignment() -> None:
    with pytest.raises(IllegalActionError, match="cannot time out an assignment"):
        apply(new_game(SEED), AssignTimeout())


def test_r4_3_r7_2_a_timed_out_call_can_end_the_game() -> None:
    """R.7.2 applies to a timed-out call like any other: five sets end the game at once."""
    state = new_game(SEED)
    for set_id in range(4):
        cards = set(set_cards(set_id))
        hands = tuple(tuple(c for c in hand if c not in cards) for hand in state.hands)
        by = tuple(1 if s == set_id else b for s, b in enumerate(state.scored_by))
        state = replace(state, hands=hands, scored_by=by)
    state, records = play(assigning(state, 0, 4), AssignTimeout())
    assert records[-1] == GameOver(outcome=Outcome.FINISHED, winner=1)


def test_r4_3_r6_2_a_timed_out_call_can_start_runout() -> None:
    """A timed-out call that leaves one team without cards starts run-out (R.6.2)."""

    def where(card: Card) -> Seat:
        return 3 + card % 2 if set_of(card) == 4 else card % 3

    hands = tuple(tuple(card for card in CARDS if where(card) == seat) for seat in range(NUM_SEATS))
    state = replace(new_game(SEED), hands=hands, current=0)
    state, records = play(assigning(state, 3, 4), AssignTimeout())
    assert isinstance(records[-1], RunoutCallerSelected)
    assert state.phase is Phase.RUNOUT


# ---------------------------------------------------------------- R.5.2 the 15-second choice


def test_r5_2_caller_who_does_not_choose_seed_chooses_among_card_holders() -> None:
    """R.5.2 (v1.1): if the caller does not choose, the game seed chooses among the scoring
    team's players holding cards."""
    state = choosing()
    assert state.choice is not None
    candidates, call_event = state.choice.candidates, state.choice.call_event
    assert len(candidates) > 1
    expected = tiebreak_seat(SEED, call_event, candidates)
    after, records = apply(state, ChoiceTimeout())
    assert records == (
        SeedChose(call_event=call_event, among=candidates, chosen=expected),
        ChoiceEvent(number=state.events, team=0, seat=expected),
    )
    assert after.current == expected
    assert after.phase is Phase.TURN
    check_consistency(after)


def test_r5_2_single_card_holder_takes_the_turn_without_a_draw() -> None:
    """With only one player holding cards there is nothing to choose between."""
    state = choosing(empty_hand(empty_hand(new_game(SEED), 1), 2))
    assert state.choice is not None
    assert state.choice.candidates == (0,)
    after, records = apply(state, ChoiceTimeout())
    assert records == (ChoiceEvent(number=state.events, team=0, seat=0),)
    assert after.current == 0


def test_r5_2_no_votes_cast_seed_chooses_among_card_holders() -> None:
    """R.5.2 (v1.1): if no votes are cast, the game seed chooses among the scoring team's
    players holding cards."""
    state = voting()
    assert state.choice is not None
    candidates, call_event = state.choice.candidates, state.choice.call_event
    expected = tiebreak_seat(SEED, call_event, candidates)
    after, records = apply(state, ChoiceTimeout())
    assert records[0] == SeedChose(call_event=call_event, among=candidates, chosen=expected)
    assert after.current == expected


def test_r5_2_votes_not_cast_are_ignored() -> None:
    """R.5.2: votes not cast within 15 seconds are ignored; the votes cast decide."""
    state, _ = play(voting(), Vote(3, 5))
    after, records = apply(state, ChoiceTimeout())
    assert records == (ChoiceEvent(number=state.events, team=1, seat=5),)
    assert after.current == 5


def test_r5_2_partial_vote_tie_is_decided_among_the_tied_seats() -> None:
    """R.5.2 (v1.1): if the votes cast tie, the game seed chooses among the tied seats only."""
    state, records = play(voting(), Vote(3, 4), Vote(4, 5))
    assert [type(record) for record in records] == [VoteCast, VoteCast]
    assert state.choice is not None
    call_event = state.choice.call_event
    expected = tiebreak_seat(SEED, call_event, (4, 5))
    after, records = apply(state, ChoiceTimeout())
    assert records[0] == SeedChose(call_event=call_event, among=(4, 5), chosen=expected)
    assert after.current == expected


@pytest.mark.parametrize("phase", [Phase.TURN, Phase.WINDOW, Phase.ASSIGN])
def test_r5_2_choice_timeout_only_during_a_choice(phase: Phase) -> None:
    states: dict[Phase, Callable[[], State]] = {
        Phase.TURN: lambda: new_game(SEED),
        Phase.WINDOW: lambda: play(new_game(SEED), OpenWindow())[0],
        Phase.ASSIGN: lambda: assigning(new_game(SEED), 0, 0),
    }
    with pytest.raises(IllegalActionError, match="cannot time out a choice"):
        apply(states[phase](), ChoiceTimeout())


# ---------------------------------------------------------------- R.8.7 stale Call presses


def ask(card: Card, success: bool) -> AskEvent:
    return AskEvent(number=0, asker=0, target=3, card=card, success=success)


def call(set_id: int) -> CallEvent:
    return CallEvent(1, 0, set_id, CallSource.WINDOW, (0,) * 6, (0,) * 6, True, 0)


@pytest.mark.parametrize(
    ("newer", "set_id", "stale"),
    [
        ((), 0, False),
        ((ask(2, success=True),), 0, True),
        ((ask(2, success=False),), 0, False),
        ((ask(8, success=True),), 0, False),
        ((call(0),), 0, True),
        ((call(1),), 0, False),
        ((ChoiceEvent(2, 0, 1), WindowOpened(3)), 0, False),
        ((ask(8, success=False), call(3), ask(5, success=True)), 0, True),
    ],
)
def test_r8_7_press_is_rejected_only_if_a_newer_event_touched_the_named_set(
    newer: tuple[Record, ...], set_id: int, stale: bool
) -> None:
    """R.8.7: if a newer event has already been applied, the press is rejected only if that
    event scored the named set or moved one of its cards; otherwise it is accepted against the
    current state."""
    assert press_is_stale(newer, set_id) is stale


def test_r8_7_press_names_a_real_set() -> None:
    with pytest.raises(ValueError, match="set"):
        press_is_stale((), 9)
