"""Tests for the after-call choice and vote (R.5), and the seed tie-break (R.5.2, v1.1)."""

from collections import Counter
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cards import Seat, next_teammate, set_cards
from fish_rules.engine import IllegalActionError, apply, tiebreak_seat
from fish_rules.events import (
    Action,
    Assign,
    ChoiceEvent,
    Choose,
    CloseWindow,
    Declare,
    OpenWindow,
    SeedChose,
    Visibility,
    Vote,
    VoteCast,
    WindowOpened,
)
from fish_rules.rng import stream
from fish_rules.state import Phase, State, check_consistency, new_game

U64 = st.integers(min_value=0, max_value=2**64 - 1)


# ---------------------------------------------------------------- helpers


def play(state: State, *actions: Action) -> State:
    for action in actions:
        state, _ = apply(state, action)
    return state


def truth(state: State, set_id: int) -> tuple[Seat, ...]:
    holders = tuple(state.holder(card) for card in set_cards(set_id))
    return tuple(holder for holder in holders if holder is not None)


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


def after_correct_call(seed: int = 1, caller: Seat = 1) -> State:
    """Seat ``caller`` (team 0) calls set 2 correctly: the caller chooses (R.5.2)."""
    state = give(new_game(seed), 2, (0, 1, 2))
    state = play(state, OpenWindow(), Declare(caller, 2), CloseWindow())
    return play(state, Assign(caller, truth(state, 2)))


def after_incorrect_call(state: State | None = None) -> State:
    """Seat 0 calls set 2 incorrectly: team 1 scores it and votes (R.5.2)."""
    state = give(state or new_game(2), 2, (3, 4))
    state = play(state, OpenWindow(), Declare(0, 2), CloseWindow())
    return play(state, Assign(0, (0,) * 6))


def votes(state: State, *ballots: tuple[Seat, Seat]) -> tuple[State, list[object]]:
    records: list[object] = []
    for seat, chosen in ballots:
        state, step = apply(state, Vote(seat, chosen))
        records.extend(step)
    return state, records


# ---------------------------------------------------------------- R.5.2 the caller chooses


def test_r5_2_caller_chooses_after_a_correct_call() -> None:
    """R.5.1: the team that scored chooses which of its players holding cards takes the turn.
    R.5.2: if the caller's team is choosing, the caller makes the choice."""
    state = after_correct_call()
    assert state.phase is Phase.CHOOSE
    assert state.choice is not None
    number = state.events
    for chosen in state.choice.candidates:
        after, records = apply(state, Choose(1, chosen))
        assert records == (ChoiceEvent(number=number, team=0, seat=chosen),)
        assert records[0].visibility is Visibility.PUBLIC
        assert after.phase is Phase.TURN
        assert after.current == chosen
        assert after.choice is None
        assert after.events == number + 1
        check_consistency(after)


def test_r5_2_only_the_caller_chooses() -> None:
    state = after_correct_call()
    for seat in (0, 2, 3, 4, 5):
        with pytest.raises(IllegalActionError, match="only the caller"):
            apply(state, Choose(seat, 1))
    with pytest.raises(IllegalActionError, match="cannot choose"):
        apply(after_incorrect_call(), Choose(0, 3))


def test_r5_1_turn_goes_only_to_a_teammate_holding_cards() -> None:
    """R.5.1: the choice is among the scoring team's players holding cards; R.9: the turn never
    falls to a player without cards."""
    state = empty_hand(give(new_game(3), 2, (0, 1)), 2)
    state = play(state, OpenWindow(), Declare(2, 2), CloseWindow())
    state = play(state, Assign(2, truth(state, 2)))
    assert state.choice is not None
    assert state.choice.candidates == (0, 1)
    for chosen, message in (
        (2, "cannot take the turn"),
        (4, "cannot take the turn"),
        (6, "chosen"),
    ):
        with pytest.raises(IllegalActionError, match=message):
            apply(state, Choose(2, chosen))


def test_r4_2_next_window_opens_once_the_new_current_player_is_set() -> None:
    """R.4.2: after a call, the after-call choice is made first; the next declaration window
    opens once the new current player is set."""
    state = after_correct_call()
    with pytest.raises(IllegalActionError, match="cannot open"):
        apply(state, OpenWindow())
    state = play(state, Choose(1, 1))
    state, records = apply(state, OpenWindow())
    assert isinstance(records[0], WindowOpened)
    assert state.current == 1


# ---------------------------------------------------------------- R.5.2 the other team votes


def test_r5_2_other_team_votes_and_only_the_outcome_is_shown() -> None:
    """R.5.2: if the other team is choosing, its members vote. Individual votes are recorded in
    the event log; only the outcome is shown to players."""
    state = after_incorrect_call()
    assert state.phase is Phase.VOTE
    assert state.choice is not None
    assert state.choice.candidates == (3, 4, 5)
    number, call_event = state.events, state.choice.call_event
    state, records = votes(state, (3, 4), (5, 4))
    assert records == [VoteCast(call_event, 3, 4), VoteCast(call_event, 5, 4)]
    assert state.phase is Phase.VOTE
    assert all(r.visibility is Visibility.LOG_ONLY for r in records if isinstance(r, VoteCast))
    state, records = votes(state, (4, 3))
    assert records == [VoteCast(call_event, 4, 3), ChoiceEvent(number=number, team=1, seat=4)]
    assert state.phase is Phase.TURN
    assert state.current == 4
    check_consistency(state)


def test_r5_2_all_members_vote_including_those_with_no_cards() -> None:
    """R.5.2: all members of the choosing team vote, including those with no cards."""
    state = after_incorrect_call(empty_hand(new_game(4), 5))
    assert state.choice is not None
    assert state.choice.candidates == (3, 4)
    state, records = votes(state, (5, 3), (3, 3), (4, 4))
    assert records[-1] == ChoiceEvent(number=state.events - 1, team=1, seat=3)


def test_r5_2_vote_rules() -> None:
    state = after_incorrect_call()
    for seat in (0, 1, 2):
        with pytest.raises(IllegalActionError, match="only members of team 1"):
            apply(state, Vote(seat, 3))
    state = play(state, Vote(3, 3))
    with pytest.raises(IllegalActionError, match="already voted"):
        apply(state, Vote(3, 4))
    with pytest.raises(IllegalActionError, match="cannot take the turn"):
        apply(state, Vote(4, 0))
    with pytest.raises(IllegalActionError, match="cannot vote"):
        apply(after_correct_call(), Vote(1, 1))


def test_r5_2_unanimous_vote() -> None:
    state, records = votes(after_incorrect_call(), (3, 5), (4, 5), (5, 5))
    assert state.current == 5
    assert not any(isinstance(record, SeedChose) for record in records)


# ---------------------------------------------------------------- R.5.2 (v1.1) the seed decides


def test_r5_2_tied_vote_is_decided_by_the_seed_among_the_tied_seats() -> None:
    """R.5.2 (v1.1): if the vote ties, the game seed chooses among the tied seats. The seed's
    choice is recorded in the event log only."""
    state = after_incorrect_call()
    assert state.choice is not None
    call_event = state.choice.call_event
    state, records = votes(state, (3, 5), (4, 3), (5, 4))
    expected = tiebreak_seat(state.seed, call_event, (3, 4, 5))
    seed_record = SeedChose(call_event=call_event, among=(3, 4, 5), chosen=expected)
    assert records[-2:] == [seed_record, ChoiceEvent(state.events - 1, 1, expected)]
    assert seed_record.visibility is Visibility.LOG_ONLY
    assert state.current == expected


def test_r5_2_two_candidates_and_three_votes_always_give_a_majority() -> None:
    """R.5.2: with two players holding cards and all three members voting, one seat always has
    more votes, so the seed is not needed."""
    state = after_incorrect_call(empty_hand(new_game(5), 5))
    state, records = votes(state, (3, 3), (4, 4), (5, 4))
    assert state.current == 4
    assert not any(isinstance(record, SeedChose) for record in records)


@given(U64, st.integers(min_value=0, max_value=2**64 - 1), st.permutations([3, 4, 5]))
def test_tiebreak_seat_is_a_frozen_function(seed: int, event: int, among: list[int]) -> None:
    """docs/determinism.md §8: ``choice`` over the seats in ascending order, from stream
    ``tiebreak`` at the call's event number. The order the seats are given in does not matter."""
    expected = stream(seed, "tiebreak", event).choice([3, 4, 5])
    assert tiebreak_seat(seed, event, among) == expected
    assert tiebreak_seat(seed, event, [*among, among[0]]) == expected


def test_tiebreak_seat_is_uniform_over_the_tied_seats() -> None:
    counts = Counter(tiebreak_seat(9, event, (0, 1, 2)) for event in range(3_000))
    assert set(counts) == {0, 1, 2}
    assert all(900 <= count <= 1_100 for count in counts.values())


def test_tiebreak_seat_rejects_non_seats() -> None:
    with pytest.raises(ValueError, match="seat"):
        tiebreak_seat(0, 0, (6,))


# ---------------------------------------------------------------- dispatch


def test_unknown_actions_are_illegal() -> None:
    with pytest.raises(IllegalActionError, match="not an action"):
        apply(new_game(6), "ask")  # pyright: ignore[reportArgumentType]
