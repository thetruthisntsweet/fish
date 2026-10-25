"""Leak tests for the projection (T2.4): a seat's view must depend only on what that seat may
know (R.2). Over random games, at every step and for every seat, the view is unchanged when
everything hidden from that seat is changed: the cards of the other seats (hand sizes kept),
the game seed, other seats' answers in an open window, and other members' votes. No view ever
holds an earlier event or a log-only record."""

import json
from collections.abc import Iterator
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import SEATS, Hand, Seat, team_seats
from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event, Visibility
from fish_rules.playout import random_game
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase, State, new_game
from fish_rules.view import PlayerView, latest_event, project

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Every seat at every step of whole games is costly: a fortieth of the profile's examples
(10 in dev, 25 in CI, 1,250 nightly)."""

PUBLIC_FIELDS = (
    "hand_sizes", "scored_by", "phase", "current", "call", "window_open", "last_event",
    "outcome", "winner",
)  # fmt: skip
"""Fields every seat sees identically (R.2.2, R.2.3, R.8.3)."""


def steps(game_seed: int, policy_seed: int) -> Iterator[tuple[State, Event | None]]:
    """Every state of a random game, starting with the deal, with its most recent event."""
    last: Event | None = None
    yield new_game(game_seed), None
    for state, records in replay(game_seed, random_game(game_seed, policy_seed)):
        last = latest_event(records, last)
        yield state, last


def scramble(state: State, seat: Seat, rng: SplitMix64) -> State:
    """``state`` with everything hidden from ``seat`` changed at random: the other seats'
    cards are dealt again among them with every hand size kept, the seed is replaced, other
    seats' window answers are redrawn, and other members' votes are redrawn."""
    others = [s for s in SEATS if s != seat]
    pool = rng.shuffled(card for s in others for card in state.hands[s])
    hands: list[Hand] = list(state.hands)
    for s in others:
        size = len(state.hands[s])
        hands[s], pool = tuple(sorted(pool[:size])), pool[size:]
    scrambled = replace(state, hands=tuple(hands), seed=rng.next_u64())
    if state.window is not None:
        in_play = state.sets_in_play()
        declared = tuple(
            d if s == seat else rng.choice((None, *in_play))
            for s, d in zip(SEATS, state.window.declared, strict=True)
        )
        responded = tuple(
            r if s == seat else rng.below(2) == 1
            for s, r in zip(SEATS, state.window.responded, strict=True)
        )
        window = replace(state.window, declared=declared, responded=responded)
        scrambled = replace(scrambled, window=window)
    if state.choice is not None:
        members = team_seats(state.choice.team)
        votes = tuple(
            v if s == seat else rng.choice((None, *state.choice.candidates))
            for s, v in zip(members, state.choice.votes, strict=True)
        )
        scrambled = replace(scrambled, choice=replace(state.choice, votes=votes))  # pyright: ignore[reportArgumentType]
    return scrambled


def contents(value: object) -> Iterator[object]:
    """Every dataclass instance inside ``value``, itself included, through fields and tuples.
    Records are dataclasses, so this finds every record a view holds."""
    if is_dataclass(value) and not isinstance(value, type):
        yield value
        for field in fields(value):
            yield from contents(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(item, int):
                yield from contents(item)  # pyright: ignore[reportUnknownArgumentType]


@settings(max_examples=GAMES, deadline=None)  # every seat at every step of a whole game
@given(U64, U64)
def test_r2_1_a_view_depends_only_on_what_the_seat_may_know(
    game_seed: int, policy_seed: int
) -> None:
    """R.2.1, R.4.3, R.5.2, R.8.3: changing everything hidden from a seat (other hands with
    their sizes kept, the seed, other seats' window answers, other members' votes) never
    changes that seat's view, its legal actions included."""
    rng = SplitMix64(policy_seed)
    phases: set[Phase] = set()
    for state, last in steps(game_seed, policy_seed):
        phases.add(state.phase)
        for seat in SEATS:
            view = project(state, seat, last)
            assert project(scramble(state, seat, rng), seat, last) == view
    assert {Phase.TURN, Phase.WINDOW, Phase.ASSIGN, Phase.OVER} <= phases


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_r2_2_public_information_is_the_same_for_every_seat(
    game_seed: int, policy_seed: int
) -> None:
    """R.2.2, R.2.3, R.8.3: hand sizes, scored sets, phase, current player, the call being
    assigned, whether a window is open, the most recent event and the outcome are the same
    in every seat's view; so is the choice in progress, apart from each seat's own vote."""
    for state, last in steps(game_seed, policy_seed):
        views = [project(state, seat, last) for seat in SEATS]
        for name in PUBLIC_FIELDS:
            assert len({getattr(view, name) for view in views}) == 1, name
        choices = {None if v.choice is None else replace(v.choice, own_vote=None) for v in views}
        assert len(choices) == 1


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_r2_2_a_view_holds_one_event_and_nothing_log_only(game_seed: int, policy_seed: int) -> None:
    """R.2.2: earlier events are not redisplayed, so a view holds at most one event, the most
    recent. R.4.3, R.5.2: no view holds a log-only record (discarded declarations, votes,
    seed choices)."""
    for state, last in steps(game_seed, policy_seed):
        for seat in SEATS:
            inside = list(contents(project(state, seat, last)))
            events = [v for v in inside if isinstance(v, AskEvent | CallEvent | ChoiceEvent)]
            assert events == ([] if last is None else [last])
            for value in inside:
                visibility = getattr(type(value), "visibility", Visibility.PUBLIC)
                assert visibility is Visibility.PUBLIC, value


def test_scramble_changes_what_is_hidden() -> None:
    """The leak test is only as strong as the scramble: it really does change other hands,
    the seed, window answers and votes, while keeping hand sizes and the seat's own hand."""
    rng = SplitMix64(1)
    for state, _ in steps(4, 4):
        if state.phase is not Phase.WINDOW:
            continue
        changed = [scramble(state, 0, rng) for _ in range(20)]
        assert all(s.hands[0] == state.hands[0] for s in changed)
        assert all(tuple(map(len, s.hands)) == tuple(map(len, state.hands)) for s in changed)
        assert any(s.hands != state.hands for s in changed)
        assert any(s.seed != state.seed for s in changed)
        assert state.window is not None
        assert any(s.window != state.window for s in changed)
        return
    raise AssertionError("no window in this game")


def test_scramble_changes_votes() -> None:
    golden = json.loads((Path(__file__).parent / "golden" / "team_votes.json").read_text("utf-8"))
    actions = [action_from_data(data) for data in golden["actions"]]
    rng = SplitMix64(2)
    for state, _ in replay(int(golden["seed"]), actions):
        if state.phase is Phase.VOTE:
            assert state.choice is not None
            seat = team_seats(state.choice.team)[0]
            changed = [scramble(state, seat, rng).choice for _ in range(20)]
            assert any(c != state.choice for c in changed)
            return
    raise AssertionError("no vote in this game")


def test_views_are_values() -> None:
    """A view compares and hashes by value, so the equality checks above mean what they say."""
    state = new_game(3)
    assert project(state, 0, None) == project(state, 0, None)
    assert isinstance(hash(project(state, 0, None)), int)
    assert isinstance(project(state, 0, None), PlayerView)
