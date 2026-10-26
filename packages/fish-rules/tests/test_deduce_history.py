"""Layer 1 constraints from a remembered history (T2.7): each kind of public fact becomes the
right constraint on the deal at the anchor, a broken history is refused, and over random games
the true deal satisfies every constraint, for every seat, the public view, and full, partial
and no memory."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import CARDS, SEATS, Card, Hand, Seat, set_cards, set_of
from fish_rules.deduce.history import (
    ALL_SEATS,
    AtLeastOne,
    Constraints,
    HistoryError,
    constraints,
    seat_mask,
    seats_in,
)
from fish_rules.engine import apply, replay
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    Assign,
    Call,
    CallEvent,
    ChoiceEvent,
    Choose,
    Event,
)
from fish_rules.playout import random_game
from fish_rules.rng import SplitMix64
from fish_rules.state import State, new_game
from fish_rules.view import PlayerView, latest_event, project

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Every seat at every event of whole games is costly: a fortieth of the profile's examples
(10 in dev, 25 in CI, 1,250 nightly)."""

# Seat k is dealt cards 9k to 9k + 8, except that seats 0 and 4 swap cards 2 and 42. Sets
# are six consecutive cards: set 0 is cards 0-5, set 1 is 6-11, and so on.
_DEALT = [list(range(9 * seat, 9 * seat + 9)) for seat in SEATS]
_DEALT[0][2], _DEALT[4][6] = 42, 2
HANDS: tuple[Hand, ...] = tuple(tuple(sorted(hand)) for hand in _DEALT)


@dataclass
class Game:
    state: State
    events: list[Event]

    def view(self, seat: Seat) -> PlayerView:
        return project(self.state, seat, self.events[-1] if self.events else None)


def play(*actions: Action) -> Game:
    """``actions`` from the deal ``HANDS``, seat 0 to play."""
    state = replace(new_game(0), hands=HANDS, current=0)
    events: list[Event] = []
    for action in actions:
        state, records = apply(state, action)
        events += [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
    return Game(state, events)


def allowed(c: Constraints, card: Card) -> tuple[Seat, ...]:
    return seats_in(c.allowed[card])


# ---------------------------------------------------------------- masks


def test_seat_masks_round_trip() -> None:
    assert seat_mask([]) == 0
    assert seat_mask(SEATS) == ALL_SEATS
    assert seats_in(seat_mask([5, 0, 3])) == (0, 3, 5)


# ---------------------------------------------------------------- each kind of fact


def test_before_any_event_only_the_deal_is_known() -> None:
    c = constraints(play().view(2), [])
    assert (c.observer, c.start, c.sizes) == (2, 0, (9,) * 6)
    for card in CARDS:
        assert allowed(c, card) == ((2,) if card in HANDS[2] else (0, 1, 3, 4, 5))
    assert c.at_least_one == ()
    assert c.moved == (None,) * 54
    assert c.in_play == (True,) * 54


def test_r3_2_r3_3_a_failed_ask() -> None:
    """Seat 0 asks seat 3 for card 9, which seat 1 holds."""
    game = play(Ask(0, 3, 9))
    by_seat_4 = constraints(game.view(4), game.events)
    assert allowed(by_seat_4, 9) == (1, 2, 5)  # not the asker, the target or the observer
    assert by_seat_4.at_least_one == (AtLeastOne(0, (6, 7, 8, 10, 11)),)
    by_seat_1 = constraints(game.view(1), game.events)
    assert allowed(by_seat_1, 9) == (1,)
    assert by_seat_1.at_least_one == (AtLeastOne(0, (6, 7, 8)),)  # 9-11 are seat 1's
    assert constraints(game.view(0), game.events).at_least_one == ()  # the asker knows


def test_r3_3_a_successful_ask_moves_the_card() -> None:
    """Seat 0, holding card 42, asks seat 4 for card 43 and gets it."""
    game = play(Ask(0, 4, 43))
    c = constraints(game.view(5), game.events)
    assert allowed(c, 43) == (4,)  # seat 4 held it
    assert c.moved[43] == 0  # and now seat 0 does
    assert c.sizes == (9,) * 6
    # Seat 0 held another card of set 7: not 43, and not 45-47, which are seat 5's.
    assert c.at_least_one == (AtLeastOne(0, (42, 44)),)


def test_a_seat_known_to_hold_a_card_of_the_set_is_not_constrained_again() -> None:
    game = play(Ask(0, 4, 43), Ask(0, 4, 44))
    c = constraints(game.view(5), game.events)
    assert c.moved[43] == c.moved[44] == 0
    # The second ask adds nothing, since seat 0 held card 43 by then. The first stands, and
    # with 44 now known to have been seat 4's, seat 0 must have been dealt 42.
    assert c.at_least_one == (AtLeastOne(0, (42,)),)


def test_a_constraint_already_certain_is_dropped() -> None:
    """Seat 4 asks in set 7; its call of set 7 then shows it was dealt 43 and 44."""
    asked = play(Ask(0, 4, 9), Ask(4, 0, 42))
    before = constraints(asked.view(1), asked.events).at_least_one
    assert AtLeastOne(4, (43, 44, 45, 46, 47)) in before
    called = play(Ask(0, 4, 9), Ask(4, 0, 42), Call(4, 7), Assign(4, (4, 4, 4, 5, 5, 5)))
    after = constraints(called.view(1), called.events).at_least_one
    assert [need.seat for need in after] == [0]  # seat 0's, from its first ask, remains


def test_r2_3_a_call_reveals_its_holders() -> None:
    """Seat 0 calls set 3, all seat 2's, then chooses itself."""
    game = play(Call(0, 3), Assign(0, (2,) * 6), Choose(0, 0))
    c = constraints(game.view(3), game.events)
    for card in set_cards(3):
        assert allowed(c, card) == (2,)
        assert not c.in_play[card]
        assert c.moved[card] is None
    assert c.in_play[0]
    worked_back = constraints(game.view(3), game.events[-1:])  # only the choice remembered
    assert worked_back.sizes == (9, 9, 3, 9, 9, 9)
    assert all(worked_back.allowed[card] == 0 for card in set_cards(3))


def test_with_partial_memory_the_anchor_is_worked_back() -> None:
    game = play(Ask(0, 4, 43), Ask(0, 4, 44), Ask(0, 4, 9), Ask(4, 0, 0))
    c = constraints(game.view(3), game.events[2:])  # the last two asks only
    assert c.start == 2
    assert c.sizes == (11, 9, 9, 9, 7, 9)  # as they were before them
    assert allowed(c, 0) == (0,)
    assert c.moved[0] == 4
    assert allowed(c, 43) == (0, 1, 2, 4, 5)  # where 43 went is forgotten


def test_with_no_memory_only_the_view_is_used() -> None:
    game = play(Ask(0, 4, 43))
    c = constraints(game.view(5), [])
    assert c.start == 1
    assert c.sizes == game.view(5).hand_sizes
    assert c.at_least_one == ()
    assert c.moved == (None,) * 54
    assert allowed(c, 43) == (0, 1, 2, 3, 4)


def test_the_public_view_uses_no_hand() -> None:
    game = play(Ask(0, 3, 9))
    c = constraints(game.view(1), game.events, use_hand=False)
    assert c.observer is None
    assert allowed(c, 9) == (1, 2, 4, 5)
    assert allowed(c, 10) == SEATS
    assert c.at_least_one == (AtLeastOne(0, (6, 7, 8, 10, 11)),)


def test_a_seat_with_no_cards_held_none() -> None:
    view = replace(play(Ask(0, 4, 43)).view(0), hand_sizes=(10, 9, 9, 9, 0, 17))
    c = constraints(view, [])
    assert all(not c.allowed[card] >> 4 & 1 for card in CARDS)


# ---------------------------------------------------------------- refused histories


def test_events_need_a_view_with_an_event() -> None:
    with pytest.raises(HistoryError, match="no event yet"):
        constraints(play().view(0), play(Ask(0, 3, 9)).events)


def test_events_must_be_one_unbroken_run() -> None:
    game = play(Ask(0, 3, 9), Ask(3, 0, 24), Ask(0, 3, 10))
    with pytest.raises(HistoryError, match="unbroken run"):
        constraints(game.view(1), [game.events[0], game.events[2]])


def test_events_must_end_at_the_views_event() -> None:
    game = play(Ask(0, 3, 9), Ask(3, 0, 24))
    with pytest.raises(HistoryError, match="most recent event"):
        constraints(game.view(1), game.events[:1])


def test_a_view_the_events_cannot_lead_to() -> None:
    miss = play(Ask(0, 3, 9))
    hit = play(Ask(0, 4, 43))
    wrong = [
        (replace(miss.view(0), hand_sizes=(9, 9, 9, 9, 9, 8)), miss),  # 53 cards for 54
        (replace(miss.view(2), hand_sizes=(8, 10, 9, 9, 9, 9)), miss),  # not a deal
        (replace(miss.view(1), hand_sizes=(9, 10, 9, 9, 9, 8)), miss),  # not its hand's size
        (replace(hit.view(0), hand=(*HANDS[0], 53)), hit),  # 43 never came
        (replace(miss.view(0), scored_by=(0, *miss.view(0).scored_by[1:])), miss),
    ]
    for view, game in wrong:
        with pytest.raises(HistoryError, match="no deal fits"):
            constraints(view, game.events)


def faked(game: Game, seat: Seat, event: Event, sizes: tuple[int, ...] | None = None) -> None:
    """``constraints`` for ``game``'s events with the last one replaced by ``event``."""
    events = [*game.events[:-1], event]
    view = replace(game.view(seat), last_event=event)
    if sizes is not None:
        view = replace(view, hand_sizes=sizes)
    constraints(view, events)


def test_a_card_that_moved_is_not_held_by_another_seat() -> None:
    game = play(Ask(0, 4, 43), Ask(0, 4, 9))
    event = AskEvent(number=1, asker=3, target=4, card=43, success=True)
    with pytest.raises(HistoryError, match="card 43 is with seat 0, not seat 4"):
        faked(game, 5, event, sizes=(10, 9, 9, 10, 7, 9))


def test_a_card_that_moved_to_a_seat_is_not_asked_for_by_it() -> None:
    game = play(Ask(0, 4, 43), Ask(0, 4, 9))
    with pytest.raises(HistoryError, match="card 43 is with seat 0"):
        faked(game, 5, replace(game.events[-1], card=43))


def test_every_card_was_held_by_someone() -> None:
    game = play(Ask(0, 3, 9))
    event = replace(game.events[0], asker=3, target=1)  # seat 1 did not hold its own card
    events = [event]
    assert constraints(replace(game.view(4), last_event=event), events).allowed[9] == 0b100101
    with pytest.raises(HistoryError, match="no seat can have held"):
        faked(game, 1, event)


def test_a_seat_asks_only_in_a_set_it_holds_a_card_of() -> None:
    game = play(Ask(0, 3, 9))
    view = replace(game.view(1), hand=(6, 7, 8, 9, 10, 11, 12, 13, 14))  # all of set 1
    with pytest.raises(HistoryError, match="cannot hold a card of"):
        constraints(view, game.events)


# ---------------------------------------------------------------- the true deal satisfies them


@dataclass(frozen=True)
class Point:
    """A moment just after an event (or at the deal), with what is true then."""

    state: State
    last: Event | None
    events: tuple[Event, ...]  # every event so far
    before: tuple[tuple[Hand, ...], ...]  # the hands just before each event, then now


def points(game_seed: int, policy_seed: int) -> Iterator[Point]:
    state = new_game(game_seed)
    events: list[Event] = []
    before: list[tuple[Hand, ...]] = []
    yield Point(state, None, (), (state.hands,))
    last: Event | None = None
    for new, records in replay(game_seed, random_game(game_seed, policy_seed)):
        found = [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
        for i, event in enumerate(found):
            before.append(state.hands if i == 0 else new.hands)
            events.append(event)
        state, last = new, latest_event(records, last)
        if found:
            yield Point(state, last, tuple(events), (*before, state.hands))


def holder(hands: Sequence[Hand], card: Card) -> Seat | None:
    return next((seat for seat in SEATS if card in hands[seat]), None)


def check(c: Constraints, point: Point) -> None:
    anchor = point.before[c.start]
    now = point.state.hands
    assert c.sizes == tuple(len(hand) for hand in anchor)
    for card in CARDS:
        then = holder(anchor, card)
        if then is None:
            assert c.allowed[card] == 0
        else:
            assert c.allowed[card] >> then & 1, (card, then)
        if c.observer is not None and card in anchor[c.observer]:
            assert c.allowed[card] == 1 << c.observer
        assert c.in_play[card] == (holder(now, card) is not None)
        if c.moved[card] is not None:
            assert holder(now, card) == c.moved[card]
        elif c.in_play[card]:
            assert holder(now, card) == then
    for need in c.at_least_one:
        assert any(holder(anchor, card) == need.seat for card in need.cards), need
        assert all(set_of(card) == set_of(need.cards[0]) for card in need.cards)


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64, U64)
def test_the_true_deal_satisfies_every_constraint(
    game_seed: int, policy_seed: int, memory_seed: int
) -> None:
    """At every event, each seat and the public view remember the whole game, the events
    since a random one, or nothing, drawn at random each time."""
    rng = SplitMix64(memory_seed)
    for point in points(game_seed, policy_seed):
        n = len(point.events)
        for seat in (*SEATS, None):
            start = rng.choice((0, rng.below(n + 1), n))
            view = project(point.state, 0 if seat is None else seat, point.last)
            remembered = point.events[start:]
            check(constraints(view, remembered, use_hand=seat is not None), point)
