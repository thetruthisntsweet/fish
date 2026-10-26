"""Layer 1 is exact (T2.7): every seat it names as a possible holder is one, and every one is
named. Over random games, for every seat, the public view and random memories:

- the true holder of every card is always among those named (nothing possible is missed by
  the constraints, and the solver keeps everything that fits them);
- each seat named for a card has a deal that fits with the card there, and each seat not
  named has none (the solver's one-flow answer agrees with asking about each seat alone);
- that deal, played forward with the same actions in the real engine, shows the seat exactly
  what it saw: the same records, and the same view at every step (the constraints miss
  nothing a seat could have learned).
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import CARDS, SEATS, Card, Hand, Seat
from fish_rules.deduce.history import AtLeastOne, Constraints, HistoryError, constraints, seat_mask
from fish_rules.deduce.solve import Deduction, deduce, example_deal, solve
from fish_rules.engine import apply, replay
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    CallEvent,
    ChoiceEvent,
    Event,
    Record,
    Visibility,
)
from fish_rules.playout import random_game
from fish_rules.rng import SplitMix64
from fish_rules.state import State, new_game
from fish_rules.view import latest_event, project

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 160)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Every seat at every event of whole games, with deals forced and replayed, is the costliest
check here: a hundred-and-sixtieth of the profile's examples (10 in dev and CI, 312
nightly)."""

NO_MOVES: tuple[None, ...] = (None,) * len(CARDS)


def synthetic(
    sizes: tuple[int, ...], allowed: dict[Card, tuple[Seat, ...]], *needs: AtLeastOne
) -> Constraints:
    """Constraints with only the cards in ``allowed`` in play, for puzzles too small to reach
    from a real game quickly."""
    masks = tuple(seat_mask(allowed.get(card, ())) for card in CARDS)
    return Constraints(
        observer=None,
        start=0,
        sizes=sizes,
        allowed=masks,
        at_least_one=needs,
        moved=NO_MOVES,
        in_play=tuple(card in allowed for card in CARDS),
    )


# ---------------------------------------------------------------- what counting adds


def test_hand_sizes_settle_a_card() -> None:
    """Cards 0 and 1 are each with seat 0 or 1, card 2 with seat 0, 1 or 2, and each of the
    three seats holds one card: card 2 must be seat 2's, though no single fact says so."""
    d = solve(synthetic((1, 1, 1, 0, 0, 0), {0: (0, 1), 1: (0, 1), 2: (0, 1, 2)}))
    assert d.possible(0) == d.possible(1) == (0, 1)
    assert d.known(2) == 2
    assert d.known(0) is None


def test_an_ask_settles_a_card() -> None:
    """Seat 0 holds one card and asked in a set it holds one of cards 0 and 1 from, so card 2,
    which seat 0 or seat 1 might hold, is seat 1's; seat 1 also holds one of 0 and 1."""
    c = synthetic((1, 2, 0, 0, 0, 0), {0: (0, 1), 1: (0, 1), 2: (0, 1)}, AtLeastOne(0, (0, 1)))
    d = solve(c)
    assert d.known(2) == 1
    assert d.possible(0) == d.possible(1) == (0, 1)


def test_cards_out_of_play_have_no_holder() -> None:
    d = solve(synthetic((1, 0, 0, 0, 0, 0), {0: (0,)}))
    assert d.possible(53) == ()
    assert d.known(53) is None
    assert d.example == ((0,), (), (), (), (), ())


def test_when_nothing_fits_it_says_so() -> None:
    impossible = synthetic((2, 0, 0, 0, 0, 0), {0: (0,), 1: (1,)})
    with pytest.raises(HistoryError, match="no deal fits"):
        solve(impossible)
    assert example_deal(impossible) is None
    possible = synthetic((1, 1, 0, 0, 0, 0), {0: (0, 1), 1: (0, 1)})
    assert example_deal(possible, {0: 1}) == ((1,), (0,), (), (), (), ())
    assert example_deal(possible, {0: 2}) is None  # not a seat card 0 may be with


def test_a_real_game_after_two_asks() -> None:
    """Seat 0, holding 42, takes 43 and 44 from seat 4: seat 5 then knows seat 0 was dealt 42,
    since it had to hold a card of the set and every other one is accounted for."""
    hands: list[list[Card]] = [list(range(9 * seat, 9 * seat + 9)) for seat in SEATS]
    hands[0][2], hands[4][6] = 42, 2
    state = replace(new_game(0), hands=tuple(tuple(sorted(h)) for h in hands), current=0)
    events: list[Event] = []
    for action in (Ask(0, 4, 43), Ask(0, 4, 44)):
        state, records = apply(state, action)
        events += [r for r in records if isinstance(r, AskEvent)]
    view = project(state, 5, events[-1])
    d = deduce(view, events)
    assert d == solve(constraints(view, events))
    assert d.known(42) == d.known(43) == d.known(44) == 0
    assert d.known(2) is None
    assert {42, 43, 44} <= set(d.example_now()[0])  # an example: not necessarily the truth
    assert tuple(len(hand) for hand in d.example_now()) == view.hand_sizes
    without_memory = deduce(view, [])
    assert without_memory.known(43) is None


# ---------------------------------------------------------------- exactness over random games


@dataclass(frozen=True)
class Game:
    actions: tuple[Action, ...]
    states: tuple[State, ...]  # states[k] is the state before actions[k]; the last is the end
    records: tuple[tuple[Record, ...], ...]  # records[k] came from actions[k]
    events: tuple[Event, ...]
    produced_by: tuple[int, ...]  # the action each event came from
    first: tuple[bool, ...]  # whether each event was its action's first


def game(game_seed: int, policy_seed: int) -> Game:
    actions = random_game(game_seed, policy_seed)
    states: list[State] = [new_game(game_seed)]
    all_records: list[tuple[Record, ...]] = []
    events: list[Event] = []
    produced_by: list[int] = []
    first: list[bool] = []
    for k, (state, records) in enumerate(replay(game_seed, actions)):
        states.append(state)
        all_records.append(records)
        found = [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
        events += found
        produced_by += [k] * len(found)
        first += [i == 0 for i in range(len(found))]
    return Game(
        actions, tuple(states), tuple(all_records), tuple(events), tuple(produced_by), tuple(first)
    )


@dataclass(frozen=True)
class Point:
    """Just after action ``step - 1``, an action that produced an event."""

    step: int
    seen: int  # events so far
    last: Event | None


def points(g: Game) -> Iterator[Point]:
    yield Point(0, 0, None)
    last: Event | None = None
    seen = 0
    for k, records in enumerate(g.records):
        last = latest_event(records, last)
        found = sum(isinstance(r, AskEvent | CallEvent | ChoiceEvent) for r in records)
        seen += found
        if found:
            yield Point(k + 1, seen, last)


def holder(hands: tuple[Hand, ...], card: Card) -> Seat | None:
    return next((seat for seat in SEATS if card in hands[seat]), None)


def anchor_hands(g: Game, start: int, point: Point) -> tuple[Hand, ...]:
    """The hands just before event ``start``, or now if nothing is remembered."""
    if start == point.seen:
        return g.states[point.step].hands
    k = g.produced_by[start]
    # Nothing moves between a call and an after-call choice its action also produced.
    return g.states[k if g.first[start] else k + 1].hands


def replay_from(g: Game, start: int, point: Point) -> int | None:
    """The action to replay from for an anchor just before event ``start``: the action that
    produced it, if it was that action's first event. With nothing remembered, the point."""
    if start == point.seen:
        return point.step
    return g.produced_by[start] if g.first[start] else None


def sound(d: Deduction, g: Game, start: int, point: Point) -> None:
    """The truth, now and at the anchor, is among what is named; the example fits."""
    now = g.states[point.step].hands
    anchor = anchor_hands(g, start, point)
    c = d.constraints
    for card in CARDS:
        true_now, true_then = holder(now, card), holder(anchor, card)
        assert (d.holders[card] == 0) == (true_now is None)
        if true_now is not None:
            assert d.holders[card] >> true_now & 1, (card, true_now, d.possible(card))
        if true_then is not None:
            assert d.anchor[card] >> true_then & 1
            assert d.anchor[card] & ~c.allowed[card] == 0
    for seat, hand in enumerate(d.example):
        assert len(hand) == c.sizes[seat]
        assert all(c.allowed[card] >> seat & 1 for card in hand)
    for need in c.at_least_one:
        assert set(need.cards) & set(d.example[need.seat])
    assert tuple(len(hand) for hand in d.example_now()) == tuple(len(hand) for hand in now)


def public(records: tuple[Record, ...]) -> tuple[Record, ...]:
    return tuple(r for r in records if r.visibility is Visibility.PUBLIC)


def replays_the_same(
    g: Game, start: int, point: Point, observer: Seat | None, deal: tuple[Hand, ...]
) -> None:
    """Played forward from ``deal`` at the anchor, the game shows ``observer`` exactly what it
    showed: every action is still legal, every public record the same, and the observer's
    view the same after every action."""
    first_step = replay_from(g, start, point)
    assert first_step is not None
    state = replace(g.states[first_step], hands=deal)
    if observer is not None:
        assert state.hands[observer] == g.states[first_step].hands[observer]
    last = g.events[start - 1] if start else None
    for k in range(first_step, point.step):
        state, records = apply(state, g.actions[k])
        assert public(records) == public(g.records[k])
        last = latest_event(records, last)
        if observer is not None:
            assert project(state, observer, last) == project(g.states[k + 1], observer, last)
        else:
            assert tuple(map(len, state.hands)) == tuple(map(len, g.states[k + 1].hands))


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64, U64)
def test_layer_1_is_exact(game_seed: int, policy_seed: int, check_seed: int) -> None:
    rng = SplitMix64(check_seed)
    g = game(game_seed, policy_seed)
    all_points = list(points(g))
    probed = {rng.below(len(all_points)) for _ in range(2)}
    for i, point in enumerate(all_points):
        state = g.states[point.step]
        for observer in (*SEATS, None):
            start = rng.choice((0, rng.below(point.seen + 1), point.seen))
            view = project(state, 0 if observer is None else observer, point.last)
            d = deduce(view, g.events[start : point.seen], use_hand=observer is not None)
            sound(d, g, start, point)
            if i not in probed or rng.below(3):
                continue
            # Each seat named for a card, and only those, has a deal with the card there.
            c = d.constraints
            for card in rng.shuffled(CARDS)[:8]:
                for seat in SEATS:
                    fits = example_deal(c, {card: seat})
                    assert (fits is not None) == bool(d.anchor[card] >> seat & 1), (card, seat)
            # A few of those deals, for seats other than the true one, replay identically.
            if replay_from(g, start, point) is None:
                continue
            anchor = anchor_hands(g, start, point)
            options = [
                (card, seat)
                for card in CARDS
                for seat in SEATS
                if d.anchor[card] >> seat & 1 and holder(anchor, card) != seat
            ]
            for card, seat in rng.shuffled(options)[:3]:
                deal = example_deal(c, {card: seat})
                assert deal is not None
                replays_the_same(g, start, point, observer, deal)
