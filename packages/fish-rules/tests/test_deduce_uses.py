"""Using Layer 1 (T2.7): the tracker an agent feeds its views to, a seat's knowledge over a
recorded game, and certain-miss asks (RQ2). Over random games the tracker agrees with
deducing from the whole history (or the run since a gap, or the last k events), knowledge
agrees with the tracker, every certain miss misses, and remembering more never finds fewer."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import SEATS, Hand, Seat
from fish_rules.deduce.games import certain_misses, knowledge
from fish_rules.deduce.solve import deduce
from fish_rules.deduce.tracker import Tracker
from fish_rules.engine import apply, replay
from fish_rules.events import Action, Ask, AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.playout import random_game
from fish_rules.rng import SplitMix64
from fish_rules.state import State, new_game
from fish_rules.view import PlayerView, latest_event, project

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 160)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games, deduced at every event several ways: a hundred-and-sixtieth of the profile's
examples (10 in dev and CI, 312 nightly)."""

# As in test_deduce_history: seat k holds cards 9k to 9k + 8, but seats 0 and 4 swap 2 and 42.
_DEALT = [list(range(9 * seat, 9 * seat + 9)) for seat in SEATS]
_DEALT[0][2], _DEALT[4][6] = 42, 2
HANDS: tuple[Hand, ...] = tuple(tuple(sorted(hand)) for hand in _DEALT)
START = replace(new_game(0), hands=HANDS, current=0)

# Seat 0 misses 9 at seat 3; seat 3 misses 24 at seat 0; each then asks again for the same
# card from the same seat, which it could know was a miss.
REPEATS: tuple[Action, ...] = (Ask(0, 3, 9), Ask(3, 0, 24), Ask(0, 3, 9), Ask(3, 0, 24))


def views(start: State, actions: tuple[Action, ...], seat: Seat) -> list[tuple[PlayerView, int]]:
    """``seat``'s view at ``start`` and after every action, with the events seen so far."""
    state, last, seen = start, None, 0
    out = [(project(state, seat, last), seen)]
    for action in actions:
        state, records = apply(state, action)
        last = latest_event(records, last)
        seen += sum(isinstance(r, AskEvent | CallEvent | ChoiceEvent) for r in records)
        out.append((project(state, seat, last), seen))
    return out


# ---------------------------------------------------------------- certain misses


@pytest.mark.parametrize(("remembered", "numbers"), [(None, (2, 3)), (2, (2, 3)), (1, ()), (0, ())])
def test_certain_misses_need_the_deciding_event_remembered(
    remembered: int | None, numbers: tuple[int, ...]
) -> None:
    found = certain_misses(START, REPEATS, remembered=remembered)
    assert tuple(event.number for event in found) == numbers
    assert all(not event.success for event in found)


def test_an_ordinary_miss_is_not_certain() -> None:
    assert certain_misses(START, REPEATS[:2]) == ()


# ---------------------------------------------------------------- knowledge over a game


def test_knowledge_at_the_deal_and_after_every_event() -> None:
    known = list(knowledge(START, REPEATS, 3))
    assert len(known) == 5
    assert known[0] == deduce(project(START, 3, None), [])
    assert 0 not in known[1].possible(9)  # seat 0 asked for card 9, so it did not hold it
    public = list(knowledge(START, REPEATS, None, remembered=1))
    assert public[0].constraints.observer is None
    assert public[-1].constraints.start == 3


# ---------------------------------------------------------------- the tracker


def test_the_tracker_remembers_each_event_once() -> None:
    tracker = Tracker(5)
    seen = views(START, REPEATS, 5)
    for view, count in seen:
        tracker.observe(view)
        assert len(tracker.events) == count
    again = tracker.observe(seen[-1][0])
    assert again is tracker.observe(seen[-1][0])  # nothing new: the same deduction back


def test_the_tracker_starts_again_after_a_gap() -> None:
    seen = views(START, REPEATS, 5)
    tracker = Tracker(5)
    tracker.observe(seen[1][0])
    tracker.observe(seen[3][0])  # event 1 was never shown
    assert [event.number for event in tracker.events] == [2]
    tracker.observe(seen[0][0])  # a view with no event yet: a new game
    assert tracker.events == []


@pytest.mark.parametrize("remembered", [0, 1, 2])
def test_the_tracker_keeps_only_the_latest_events(remembered: int) -> None:
    tracker = Tracker(5, remembered=remembered)
    for view, _ in views(START, REPEATS, 5):
        tracker.observe(view)
    assert [event.number for event in tracker.events] == [0, 1, 2, 3][4 - remembered :]


def test_the_tracker_refuses_misuse() -> None:
    with pytest.raises(ValueError, match="0 or more"):
        Tracker(0, remembered=-1)
    with pytest.raises(ValueError, match="follows seat 0, not seat 1"):
        Tracker(0).observe(project(START, 1, None))


# ---------------------------------------------------------------- over random games


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64, U64)
def test_the_tracker_and_knowledge_agree_with_deducing_directly(
    game_seed: int, policy_seed: int, choice_seed: int
) -> None:
    """A tracker shown every view, one remembering the last few events, and one shown nine
    views in ten, over a whole game. Between events the view changes in nothing Layer 1 uses,
    so each tracker must hand back the deduction it already made."""
    rng = SplitMix64(choice_seed)
    seat = rng.below(len(SEATS))
    remembered = rng.choice((None, 0, 1, 1 + rng.below(20)))
    trackers = {"full": Tracker(seat), "limited": Tracker(seat, remembered=remembered)}
    gappy = Tracker(seat)
    actions = random_game(game_seed, policy_seed)
    known = knowledge(new_game(game_seed), actions, seat)
    previous = {name: tracker.observe(project(new_game(game_seed), seat, None))
                for name, tracker in trackers.items()}  # fmt: skip
    assert next(known) == previous["full"] == deduce(project(new_game(game_seed), seat, None), [])
    events: list[Event] = []
    last: Event | None = None
    shown: int | None = None  # the last event number the gappy tracker was shown
    run_start = 0
    for state, records in replay(game_seed, actions):
        last = latest_event(records, last)
        new = [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
        events += new
        view = project(state, seat, last)
        recent = events[-remembered:] if remembered else events if remembered is None else []
        for name, tracker in trackers.items():
            deduction = tracker.observe(view)
            if new:
                assert deduction == deduce(view, events if name == "full" else recent)
            else:
                assert deduction is previous[name]
            previous[name] = deduction
        if new:
            assert next(known) == previous["full"]
        if rng.below(10):  # the gappy tracker is shown nine views in ten
            n = None if last is None else last.number
            if n is not None and (shown is None or n not in (shown, shown + 1)):
                run_start = n
            if n != shown:
                assert gappy.observe(view) == deduce(view, events[run_start:] if events else [])
            shown = n
    assert next(known, None) is None
    # Every certain miss misses, and remembering more never finds fewer.
    found = [set(certain_misses(new_game(game_seed), actions, remembered=k)) for k in (0, 1, 5)]
    found.append(set(certain_misses(new_game(game_seed), actions)))
    assert all(not event.success for event in found[-1])
    assert found[0] <= found[1] <= found[2] <= found[3]
