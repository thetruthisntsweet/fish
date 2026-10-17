"""Tests for declaration windows (R.4.2, R.4.3, R.8.1), two-step calls (R.4), what follows a
call (R.5.1, R.7.2) and the engine's input handling for them."""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cards import SETS, Seat, next_teammate, set_cards, team_of, team_seats
from fish_rules.engine import IllegalActionError, apply, assignment_violation
from fish_rules.events import (
    Action,
    Assign,
    Call,
    CallEvent,
    CloseWindow,
    DeclarationDiscarded,
    Declare,
    Declared,
    GameOver,
    OpenWindow,
    Pass,
    Visibility,
    WindowClosed,
    WindowOpened,
)
from fish_rules.priority import priority_order
from fish_rules.state import (
    CallSource,
    Outcome,
    PendingCall,
    PendingChoice,
    Phase,
    State,
    Window,
    check_consistency,
    new_game,
)

U64 = st.integers(min_value=0, max_value=2**64 - 1)


# ---------------------------------------------------------------- helpers


def current(state: State) -> Seat:
    assert state.current is not None
    return state.current


def truth(state: State, set_id: int) -> tuple[Seat, ...]:
    """The true holders of ``set_id``'s cards, in card order."""
    holders = tuple(state.holder(card) for card in set_cards(set_id))
    assert all(holder is not None for holder in holders)
    return tuple(holder for holder in holders if holder is not None)


def give(state: State, set_id: int, seats: tuple[Seat, ...]) -> State:
    """``state`` with the cards of ``set_id`` dealt to ``seats`` in turn (cards conserved)."""
    cards = set_cards(set_id)
    hands = [tuple(card for card in hand if card not in cards) for hand in state.hands]
    for i, card in enumerate(cards):
        seat = seats[i % len(seats)]
        hands[seat] = tuple(sorted((*hands[seat], card)))
    return replace(state, hands=tuple(hands))


def empty_hand(state: State, seat: Seat) -> State:
    """``state`` with ``seat``'s cards moved to its next teammate."""
    mate = next_teammate(seat)
    hands = list(state.hands)
    hands[mate] = tuple(sorted((*hands[mate], *hands[seat])))
    hands[seat] = ()
    return replace(state, hands=tuple(hands))


def scored(state: State, set_id: int, team: int) -> State:
    cards = set(set_cards(set_id))
    hands = tuple(tuple(card for card in hand if card not in cards) for hand in state.hands)
    by = tuple(team if s == set_id else b for s, b in enumerate(state.scored_by))
    return replace(state, hands=hands, scored_by=by)


def play(state: State, *actions: Action) -> State:
    for action in actions:
        state, _ = apply(state, action)
    return state


def window_call(state: State, seat: Seat, set_id: int) -> State:
    """Open a window, have ``seat`` alone declare ``set_id``, close it: ``seat`` assigns next."""
    return play(state, OpenWindow(), Declare(seat, set_id), CloseWindow())


# ---------------------------------------------------------------- R.4.2 opening windows


def test_r4_2_window_opens_before_the_current_player_acts() -> None:
    """R.4.2: in the environment a window opens at the start of the game, before the current
    player acts. With no declaration, the current player may then ask or call."""
    state = new_game(1)
    opened, records = apply(state, OpenWindow())
    assert opened.phase is Phase.WINDOW
    assert records == (WindowOpened(index=0),)
    assert opened.current == state.current
    closed, records = apply(opened, CloseWindow())
    assert closed.phase is Phase.TURN
    assert closed.current == state.current
    assert records == (WindowClosed(index=0, caller=None, set_id=None),)
    check_consistency(closed)


def test_r8_1_window_index_counts_windows_opened_earlier() -> None:
    """R.8.1: a window's index is the number of declaration windows opened earlier in the game,
    starting from 0."""
    state = new_game(2)
    for index in range(5):
        state, records = apply(state, OpenWindow())
        assert records == (WindowOpened(index=index),)
        state, _ = apply(state, CloseWindow())
    assert state.windows_opened == 5


@pytest.mark.parametrize("phase", [Phase.WINDOW, Phase.ASSIGN, Phase.CHOOSE, Phase.VOTE])
def test_r8_3_no_window_during_a_window_assignment_or_choice(phase: Phase) -> None:
    """R.8.3: Call presses during a call assignment or an after-call choice are rejected; a
    window opens only on a turn."""
    state = new_game(3)
    state = replace(
        state,
        phase=phase,
        window=Window(0, (None,) * 6, (False,) * 6) if phase is Phase.WINDOW else None,
        call=PendingCall(0, 0, CallSource.TURN) if phase is Phase.ASSIGN else None,
        choice=PendingChoice(0, (0,), 0, (None, None, None), 0)
        if phase in (Phase.CHOOSE, Phase.VOTE)
        else None,
    )
    with pytest.raises(IllegalActionError, match="cannot open a declaration window"):
        apply(state, OpenWindow())


def test_r6_2_no_window_during_runout() -> None:
    """R.6.2: during run-out only the selected caller may call; no window opens."""
    with pytest.raises(IllegalActionError, match="cannot open a declaration window"):
        apply(replace(new_game(4), phase=Phase.RUNOUT), OpenWindow())


# ---------------------------------------------------------------- R.4.2 declaring


def test_r4_2_any_player_may_declare_out_of_turn_and_with_no_cards() -> None:
    """R.4.2: any player may call in any window, including out of turn and including players
    with no cards. Declarations are recorded but not shown (R.4.3, R.8.3)."""
    state = empty_hand(new_game(5), 4)
    state, _ = apply(state, OpenWindow())
    for seat in (0, 1, 2, 3, 4, 5):
        state, records = apply(state, Declare(seat, seat))
        assert records == (Declared(window=0, seat=seat, set_id=seat),)
        assert records[0].visibility is Visibility.LOG_ONLY
    assert state.window is not None
    assert state.window.declared == (0, 1, 2, 3, 4, 5)
    check_consistency(state)


def test_r4_6_declaration_must_name_a_set_in_play() -> None:
    """R.4.6: a valid call names one set still in play; invalid calls are rejected at input."""
    state = play(scored(new_game(6), 3, 0), OpenWindow())
    with pytest.raises(IllegalActionError, match="already been scored"):
        apply(state, Declare(0, 3))
    for bad in (9, -1, True):
        with pytest.raises(IllegalActionError, match="set"):
            apply(state, Declare(0, bad))


def test_each_seat_responds_once_per_window() -> None:
    state = play(new_game(7), OpenWindow(), Declare(1, 0), Pass(2))
    assert state.window is not None
    assert state.window.responded == (False, True, True, False, False, False)
    assert state.window.declared == (None, 0, None, None, None, None)
    for action in (Declare(1, 2), Pass(1), Declare(2, 2), Pass(2)):
        with pytest.raises(IllegalActionError, match="already responded"):
            apply(state, action)


def test_declare_pass_and_close_need_an_open_window() -> None:
    state = new_game(8)
    for action, what in ((Declare(0, 0), "declare"), (Pass(0), "pass"), (CloseWindow(), "close")):
        with pytest.raises(IllegalActionError, match=f"cannot {what}"):
            apply(state, action)


def test_malformed_seats_are_illegal_actions() -> None:
    state = play(new_game(9), OpenWindow())
    for action in (Declare(6, 0), Pass(-1), Declare(True, 0)):
        with pytest.raises(IllegalActionError, match="seat"):
            apply(state, action)


# ---------------------------------------------------------------- R.4.3 closing windows


@given(U64, st.integers(min_value=0, max_value=50), st.sets(st.integers(0, 5), min_size=1))
def test_r4_3_r8_1_highest_priority_declaration_proceeds(
    seed: int, index: int, declarers: set[int]
) -> None:
    """R.4.3: when the window closes, the declared call with the highest priority (R.8.1, from
    the seed and the window's index) proceeds and all others are discarded. Discarded
    declarations are not shown to any player but are recorded in the event log."""
    state = replace(new_game(seed), windows_opened=index)
    state = play(state, OpenWindow(), *(Declare(seat, seat) for seat in sorted(declarers)))
    state, records = apply(state, CloseWindow())

    order = priority_order(seed, index)
    ranked = [seat for seat in order if seat in declarers]
    winner = ranked[0]
    assert records[0] == WindowClosed(index=index, caller=winner, set_id=winner)
    assert records[0].visibility is Visibility.PUBLIC
    assert records[1:] == tuple(
        DeclarationDiscarded(window=index, seat=seat, set_id=seat) for seat in ranked[1:]
    )
    assert all(record.visibility is Visibility.LOG_ONLY for record in records[1:])
    assert state.phase is Phase.ASSIGN
    assert state.call == PendingCall(caller=winner, set_id=winner, source=CallSource.WINDOW)
    assert state.window is None
    check_consistency(state)


def test_r4_3_passes_do_not_proceed() -> None:
    state = play(new_game(10), OpenWindow(), *(Pass(seat) for seat in range(6)))
    state, records = apply(state, CloseWindow())
    assert state.phase is Phase.TURN
    assert records == (WindowClosed(index=0, caller=None, set_id=None),)


# ---------------------------------------------------------------- R.4.2 calling on a turn


def test_r4_2_current_player_calls_after_an_empty_window() -> None:
    """R.4.2: if a window closes with no declaration, the current player may ask or call; a call
    made this way proceeds directly to the assignment step."""
    state = play(new_game(11), OpenWindow(), CloseWindow())
    seat = current(state)
    after, records = apply(state, Call(seat, 4))
    assert records == ()
    assert after.phase is Phase.ASSIGN
    assert after.call == PendingCall(caller=seat, set_id=4, source=CallSource.TURN)
    check_consistency(after)


def test_r3_1_only_the_current_player_calls_on_a_turn() -> None:
    """R.3.1: the current player must either ask or call; others call only in windows."""
    state = new_game(12)
    other = (current(state) + 1) % 6
    with pytest.raises(IllegalActionError, match="only the current player"):
        apply(state, Call(other, 0))
    with pytest.raises(IllegalActionError, match="already been scored"):
        apply(scored(state, 0, 1), Call(current(state), 0))
    with pytest.raises(IllegalActionError, match="cannot call"):
        apply(play(state, OpenWindow()), Call(current(state), 0))


# ---------------------------------------------------------------- R.4.1, R.4.6 assignments


def test_r4_6_assignment_validity_needs_no_hidden_information() -> None:
    """R.4.1, R.4.6: valid if all six cards go to members of the caller's team."""
    assert assignment_violation(0, (0, 1, 2, 0, 1, 2)) is None
    assert assignment_violation(4, (3, 3, 3, 3, 3, 3)) is None
    assert assignment_violation(0, (0, 1, 2, 0, 1)) is not None
    assert assignment_violation(0, (0, 1, 2, 0, 1, 2, 0)) is not None
    assert assignment_violation(0, (0, 1, 2, 0, 1, 3)) is not None


@pytest.mark.parametrize(
    ("holders", "message"),
    [
        ((0, 1, 2, 0, 1), "six holders"),
        ((0, 1, 2, 0, 1, 4), "not on the caller's team"),
        ((0, 1, 2, 0, 1, 6), "assigned holder"),
        ((0, 1, 2, 0, 1, True), "assigned holder"),
    ],
)
def test_r4_6_invalid_assignments_are_rejected_at_input(
    holders: tuple[int, ...], message: str
) -> None:
    """R.4.6: invalid calls are rejected at input and never scored."""
    state = window_call(new_game(13), 0, 2)
    with pytest.raises(IllegalActionError, match=message):
        apply(state, Assign(0, holders))
    assert state.phase is Phase.ASSIGN


def test_r4_3_only_the_caller_assigns() -> None:
    """R.4.3: the caller whose call proceeds assigns the six cards."""
    state = window_call(new_game(14), 0, 2)
    with pytest.raises(IllegalActionError, match="only the caller"):
        apply(state, Assign(1, (0, 1, 2, 0, 1, 2)))
    with pytest.raises(IllegalActionError, match="cannot assign"):
        apply(new_game(14), Assign(0, (0, 1, 2, 0, 1, 2)))


# ---------------------------------------------------------------- R.4.4, R.4.5 resolving


def test_r4_4_correct_call_scores_for_the_callers_team() -> None:
    """R.4.4: a call is correct if every card is held by the teammate it was assigned to, and
    scores the set for the caller's team. R.4.5: all six cards leave play. R.2.3: the true
    holders are revealed. R.5.2: the caller then chooses who takes the turn."""
    state = give(new_game(15), 6, (0, 1))
    state = window_call(state, 2, 6)
    holders = truth(state, 6)
    state_events = state.events
    after, records = apply(state, Assign(2, holders))
    assert records == (
        CallEvent(
            number=state_events,
            caller=2,
            set_id=6,
            source=CallSource.WINDOW,
            assignment=holders,
            holders=holders,
            correct=True,
            scored_by=0,
        ),
    )
    assert after.scored_by[6] == 0
    assert all(after.holder(card) is None for card in set_cards(6))
    assert after.events == state_events + 1
    assert after.phase is Phase.CHOOSE
    assert after.choice == PendingChoice(
        team=0,
        candidates=tuple(seat for seat in team_seats(0) if after.hands[seat]),
        chooser=2,
        votes=(None, None, None),
        call_event=state_events,
    )
    assert after.current is None
    check_consistency(after)


def test_r4_4_incorrect_call_scores_for_the_other_team() -> None:
    """R.4.4: an incorrect call scores the set for the other team. R.4.5: either way, all six
    cards leave play, from whichever hands hold them, opponents' included. R.5.2: the other
    team then votes."""
    state = give(new_game(16), 1, (0, 4))
    state = window_call(state, 0, 1)
    after, records = apply(state, Assign(0, (0, 0, 0, 0, 0, 0)))
    (record,) = records
    assert isinstance(record, CallEvent)
    assert not record.correct
    assert record.scored_by == 1
    assert record.holders == (0, 4, 0, 4, 0, 4)
    assert after.scored_by[1] == 1
    assert all(after.holder(card) is None for card in set_cards(1))
    assert after.phase is Phase.VOTE
    assert after.choice is not None
    assert (after.choice.team, after.choice.chooser) == (1, None)
    check_consistency(after)


def test_r4_6_assigning_to_a_teammate_with_no_cards_is_valid_but_incorrect() -> None:
    """R.4.6: assigning a card to a teammate who holds no cards is valid; it simply makes the
    call incorrect."""
    state = empty_hand(give(new_game(17), 0, (0, 2)), 1)
    state = window_call(state, 0, 0)
    holders = (1, *truth(state, 0)[1:])
    after, records = apply(state, Assign(0, holders))
    (record,) = records
    assert isinstance(record, CallEvent)
    assert not record.correct
    assert after.scored_by[0] == 1


def test_r4_2_player_with_no_cards_may_call() -> None:
    """R.4.2: any player may call, including players with no cards. R.5.1: only teammates
    holding cards can be given the turn."""
    state = empty_hand(give(new_game(18), 8, (3, 5)), 4)
    state = window_call(state, 4, 8)
    after, records = apply(state, Assign(4, truth(state, 8)))
    (record,) = records
    assert isinstance(record, CallEvent)
    assert record.correct
    assert after.choice is not None
    assert after.choice.chooser == 4
    assert 4 not in after.choice.candidates
    check_consistency(after)


def test_r4_2_call_on_a_turn_resolves_the_same_way() -> None:
    state = play(new_game(19), OpenWindow(), CloseWindow())
    seat = current(state)
    team = team_of(seat)
    state = give(state, 3, team_seats(team))
    state = play(state, Call(seat, 3))
    after, records = apply(state, Assign(seat, truth(state, 3)))
    (record,) = records
    assert isinstance(record, CallEvent)
    assert record.source is CallSource.TURN
    assert record.correct
    assert after.scored_by[3] == team


# ---------------------------------------------------------------- R.7.2 a call that ends the game


@pytest.mark.parametrize("correct", [True, False])
def test_r7_2_call_reaching_five_sets_ends_the_game_with_no_choice(correct: bool) -> None:
    """R.7.1: the game ends when a team claims five or more sets. R.7.2: if a call brings a team
    to five sets, the game ends immediately; no after-call choice is made."""
    state = new_game(20)
    for set_id in range(4):
        state = scored(state, set_id, 1)
    state = give(state, 4, (3, 4))
    caller = 3 if correct else 0
    state = window_call(state, caller, 4)
    holders = truth(state, 4) if correct else (0,) * 6
    after, records = apply(state, Assign(caller, holders))
    assert isinstance(records[0], CallEvent)
    assert records[1:] == (GameOver(outcome=Outcome.FINISHED, winner=1),)
    assert after.phase is Phase.OVER
    assert after.outcome is Outcome.FINISHED
    assert after.choice is None
    assert after.current is None
    check_consistency(after)
    with pytest.raises(IllegalActionError, match="game is over"):
        apply(after, OpenWindow())


# ---------------------------------------------------------------- R.9 cards are conserved


@given(U64, st.data())
def test_r9_any_valid_call_conserves_cards(seed: int, data: st.DataObject) -> None:
    """R.9: cards in hands plus cards in scored sets always total 54, whatever is called."""
    state = new_game(seed)
    caller = data.draw(st.integers(0, 5))
    set_id = data.draw(st.sampled_from(SETS))
    holders = tuple(data.draw(st.sampled_from(team_seats(team_of(caller)))) for _ in range(6))
    state = window_call(state, caller, set_id)
    after, (record, *_) = apply(state, Assign(caller, holders))
    assert isinstance(record, CallEvent)
    assert record.correct == (holders == record.holders)
    assert sum(len(hand) for hand in after.hands) == 54 - 6
    check_consistency(after)
