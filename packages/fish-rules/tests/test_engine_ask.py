"""Tests for asking (R.3), the ask limit (R.8.2) and the engine's input handling."""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cards import (
    CARDS,
    SEATS,
    Seat,
    next_teammate,
    opponent_team,
    set_of,
    team_of,
    team_seats,
)
from fish_rules.engine import IllegalActionError, apply, ask_violation, legal_asks
from fish_rules.events import Ask, AskEvent, GameOver
from fish_rules.state import MAX_ASKS, Outcome, Phase, State, Window, check_consistency, new_game

U64 = st.integers(min_value=0, max_value=2**64 - 1)


def sizes(state: State) -> tuple[int, ...]:
    return tuple(len(hand) for hand in state.hands)


def current(state: State) -> Seat:
    assert state.current is not None
    return state.current


def asks_of(state: State) -> tuple[Ask, ...]:
    seat = current(state)
    return legal_asks(seat, state.hands[seat], sizes(state))


def hit_and_miss(state: State) -> tuple[Ask, Ask]:
    """A legal ask that succeeds and one that fails, from the current player."""
    asks = asks_of(state)
    hit = next(a for a in asks if a.card in state.hands[a.target])
    miss = next(a for a in asks if a.card not in state.hands[a.target])
    return hit, miss


def with_hand_given_away(state: State, seat: Seat) -> State:
    """``state`` with all of ``seat``'s cards moved to its next teammate."""
    mate = next_teammate(seat)
    hands = list(state.hands)
    hands[mate] = tuple(sorted((*hands[mate], *hands[seat])))
    hands[seat] = ()
    return replace(state, hands=tuple(hands))


# ---------------------------------------------------------------- R.3.1 who may ask


def test_r3_1_only_the_current_player_may_ask() -> None:
    """R.3.1: the current player must either ask or call. No one else may ask."""
    state = new_game(1)
    ask = asks_of(state)[0]
    for seat in SEATS:
        if seat != current(state):
            with pytest.raises(IllegalActionError, match="only the current player"):
                apply(state, replace(ask, seat=seat))


@pytest.mark.parametrize("phase", [Phase.WINDOW, Phase.RUNOUT])
def test_r3_1_no_asking_outside_a_turn(phase: Phase) -> None:
    """R.3.1, R.4.2: no ask while a window is open; R.6.2: asking ends at run-out."""
    state = new_game(2)
    window = Window(0, (None,) * 6, (False,) * 6) if phase is Phase.WINDOW else None
    with pytest.raises(IllegalActionError, match="no one may ask now"):
        apply(replace(state, phase=phase, window=window), asks_of(state)[0])


def test_r7_nothing_is_legal_after_the_game_ends() -> None:
    state = replace(new_game(3), phase=Phase.OVER, outcome=Outcome.FINISHED)
    with pytest.raises(IllegalActionError, match="game is over"):
        apply(state, asks_of(new_game(3))[0])


# ---------------------------------------------------------------- R.3.2 legal asks


def test_r3_2_must_ask_an_opponent() -> None:
    """R.3.2: an ask names one opponent."""
    state = new_game(4)
    ask = asks_of(state)[0]
    for teammate in team_seats(team_of(ask.seat)):
        with pytest.raises(IllegalActionError, match="must be an opponent"):
            apply(state, replace(ask, target=teammate))


def test_r3_2_r6_1_cannot_ask_a_player_with_no_cards() -> None:
    """R.3.2: the opponent must hold at least one card. R.6.1: a player with no cards
    cannot be asked."""
    state = new_game(5)
    ask = asks_of(state)[0]
    state = with_hand_given_away(state, ask.target)
    with pytest.raises(IllegalActionError, match="holds no cards"):
        apply(state, ask)
    assert all(a.target != ask.target for a in asks_of(state))


def test_r3_2_cannot_ask_for_a_card_you_hold() -> None:
    """R.3.2: the asker does not hold the card itself."""
    state = new_game(6)
    seat = current(state)
    target = team_seats(opponent_team(team_of(seat)))[0]
    with pytest.raises(IllegalActionError, match="already holds"):
        apply(state, Ask(seat, target, state.hands[seat][0]))


def test_r3_2_must_hold_a_card_of_the_set() -> None:
    """R.3.2: the asker holds at least one card of that card's set."""
    state = new_game(7)
    seat = current(state)
    held_sets = {set_of(card) for card in state.hands[seat]}
    card = next(card for card in CARDS if set_of(card) not in held_sets)
    target = team_seats(opponent_team(team_of(seat)))[0]
    with pytest.raises(IllegalActionError, match="no card of that set"):
        apply(state, Ask(seat, target, card))


@pytest.mark.parametrize(
    ("ask", "message"),
    [
        (Ask(6, 0, 0), "seat"),
        (Ask(-1, 0, 0), "seat"),
        (Ask(0, 6, 0), "target"),
        (Ask(0, 3, 54), "card"),
        (Ask(0, 3, True), "card"),
    ],
)
def test_malformed_asks_are_illegal_actions(ask: Ask, message: str) -> None:
    """R.8.7: an illegal action is rejected and the player acts again; malformed values are
    illegal actions too, not crashes."""
    with pytest.raises(IllegalActionError, match=message):
        apply(new_game(8), ask)


@given(U64)
def test_r3_2_legal_asks_match_the_rule_exactly(seed: int) -> None:
    """R.3.2: ``legal_asks`` lists exactly the (target, card) pairs ``ask_violation`` allows."""
    state = new_game(seed)
    for seat in SEATS:
        hand, hand_sizes = state.hands[seat], sizes(state)
        brute = tuple(
            Ask(seat, target, card)
            for target in SEATS
            for card in CARDS
            if ask_violation(seat, hand, target, hand_sizes[target], card) is None
        )
        assert sorted(legal_asks(seat, hand, hand_sizes), key=lambda a: (a.target, a.card)) == (
            sorted(brute, key=lambda a: (a.target, a.card))
        )
        assert legal_asks(seat, hand, hand_sizes) == tuple(
            sorted(legal_asks(seat, hand, hand_sizes), key=lambda a: (a.target, a.card))
        )


def test_r3_2_legality_needs_only_own_hand_and_hand_sizes() -> None:
    """Legality depends on the asker's hand and public hand sizes only, so it can be checked
    against hands the asker might hold (Layer 2, RQ2)."""
    assert legal_asks(0, (0, 1), (2, 0, 0, 3, 0, 1)) == tuple(
        Ask(0, target, card) for target in (3, 5) for card in (2, 3, 4, 5)
    )
    assert legal_asks(4, (53,), (1, 1, 0, 0, 1, 0)) == tuple(
        Ask(4, target, card) for target in (0, 1) for card in (48, 49, 50, 51, 52)
    )
    assert legal_asks(1, (7,), (0, 1, 0, 0, 0, 0)) == ()


def test_r9_no_legal_ask_when_holding_whole_sets() -> None:
    """R.9: if no legal ask exists, the current player must call. Holding every card of each
    set you hold leaves nothing to ask for."""
    assert legal_asks(0, (0, 1, 2, 3, 4, 5), (6, 0, 0, 1, 1, 1)) == ()


# ---------------------------------------------------------------- R.3.3 resolving an ask


def test_r3_3_successful_ask_moves_the_card_and_keeps_the_turn() -> None:
    """R.3.3: if the opponent holds the card, it moves to the asker, who keeps the turn."""
    state = new_game(9)
    hit, _ = hit_and_miss(state)
    after, records = apply(state, hit)
    assert hit.card in after.hands[hit.seat]
    assert hit.card not in after.hands[hit.target]
    assert after.hands[hit.seat] == tuple(sorted(after.hands[hit.seat]))
    assert after.current == hit.seat
    assert after.phase is Phase.TURN
    assert records == (AskEvent(0, hit.seat, hit.target, hit.card, success=True),)
    assert (after.events, after.asks) == (1, 1)
    check_consistency(after)


def test_r3_3_failed_ask_passes_the_turn_to_the_opponent_asked() -> None:
    """R.3.3: otherwise the turn passes to the opponent who was asked."""
    state = new_game(9)
    _, miss = hit_and_miss(state)
    after, records = apply(state, miss)
    assert after.hands == state.hands
    assert after.current == miss.target
    assert records == (AskEvent(0, miss.seat, miss.target, miss.card, success=False),)
    check_consistency(after)


def test_input_state_is_unchanged() -> None:
    """The engine returns a new state; the old one is still valid (docs/determinism.md §8)."""
    state = new_game(10)
    before = (state.hands, state.current, state.events)
    apply(state, hit_and_miss(state)[0])
    assert (state.hands, state.current, state.events) == before


@given(U64, st.data())
def test_r9_asks_conserve_cards_and_turn_never_falls_to_a_player_without_cards(
    seed: int, data: st.DataObject
) -> None:
    """R.9: cards are conserved, and the turn never falls to a player without cards. Event
    numbers run 0, 1, 2, ... (docs/determinism.md §8)."""
    state = new_game(seed)
    for step in range(40):
        asks = asks_of(state)
        safe = [  # stop short of run-out (R.6.2), which subtask 7 adds
            a
            for a in asks
            if not (
                a.card in state.hands[a.target]
                and sum(len(state.hands[s]) for s in team_seats(team_of(a.target))) == 1
            )
        ]
        if not safe:
            break
        state, records = apply(state, data.draw(st.sampled_from(safe)))
        check_consistency(state)
        assert len(state.hands[current(state)]) > 0
        assert records[0] == replace(records[0], number=step)
        assert (state.events, state.asks) == (step + 1, step + 1)


# ---------------------------------------------------------------- R.8.2 the ask limit


def test_r8_2_game_reaching_1000_asks_ends_unfinished() -> None:
    """R.8.2: the engine ends any game that reaches 1,000 asks as unfinished."""
    state = replace(new_game(11), asks=MAX_ASKS - 2)
    state, records = apply(state, hit_and_miss(state)[1])
    assert state.phase is Phase.TURN
    assert len(records) == 1
    state, records = apply(state, asks_of(state)[0])
    assert state.asks == MAX_ASKS
    assert state.phase is Phase.OVER
    assert state.outcome is Outcome.UNFINISHED
    assert state.current is None
    assert isinstance(records[0], AskEvent)
    assert records[1] == GameOver(outcome=Outcome.UNFINISHED, winner=None)
    check_consistency(state)
    with pytest.raises(IllegalActionError, match="game is over"):
        apply(state, asks_of(new_game(11))[0])
