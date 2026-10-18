"""Whole games: replay, the action codec, who may act, and the R.9 invariants checked at every
step of random games played under environment mechanics (fish_rules.playout)."""

from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import CARDS, SEATS, SETS, team_of, team_seats
from fish_rules.codec import action_from_data, action_to_data
from fish_rules.engine import IllegalActionError, acting_seats, apply, legal_actions, replay
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    Assign,
    AssignTimeout,
    Call,
    CallEvent,
    ChoiceEvent,
    ChoiceTimeout,
    Choose,
    CloseWindow,
    Declare,
    Event,
    OpenWindow,
    Pass,
    Record,
    Vote,
)
from fish_rules.playout import random_game
from fish_rules.state import SETS_TO_WIN, Outcome, Phase, State, check_consistency, new_game

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 10)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games are slower than single steps: a tenth of the profile's examples (10 in dev, 100
in CI, 5,000 nightly)."""


def numbered(records: list[Record]) -> list[Event]:
    return [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]


# ---------------------------------------------------------------- R.9 over whole games


@settings(max_examples=GAMES)
@given(U64, U64)
def test_r9_invariants_hold_at_every_step_of_random_games(game_seed: int, policy_seed: int) -> None:
    """R.9: the turn never falls to a player without cards; the current player can always act;
    at most nine calls occur; cards are conserved; a correct out-of-turn call lets the caller's
    team choose who moves next. Also: event numbers run 0, 1, 2, ... (docs/determinism.md §8),
    and every game ends (R.7, R.8.2)."""
    actions = random_game(game_seed, policy_seed)
    records: list[Record] = []
    state = new_game(game_seed)
    for state, step in replay(game_seed, actions):
        records.extend(step)
        check_consistency(state)
        if state.phase in (Phase.TURN, Phase.RUNOUT):
            assert state.current is not None
            assert legal_actions(state, state.current)
        if state.phase is Phase.TURN:
            assert state.current is not None
            assert state.hands[state.current], "R.9: the turn fell to a player without cards"
        window_complete = state.window is not None and all(state.window.responded)
        if state.phase is not Phase.OVER and not window_complete:
            assert acting_seats(state), "someone must be able to act"

    assert state.phase is Phase.OVER
    calls = [r for r in records if isinstance(r, CallEvent)]
    assert len(calls) <= len(SETS)
    assert [event.number for event in numbered(records)] == list(range(state.events))
    if state.outcome is Outcome.FINISHED:
        winner = state.winner()
        assert winner is not None
        assert state.score(winner) >= SETS_TO_WIN > state.score(1 - winner)
    for before, after in pairwise(records):
        if isinstance(before, CallEvent) and isinstance(after, ChoiceEvent):
            assert after.team == before.scored_by
            if before.correct:
                assert after.team == team_of(before.caller), "R.9: initiative after a correct call"


def test_random_games_are_reproducible() -> None:
    """A (game seed, policy seed) pair always gives the same game."""
    assert random_game(5, 6) == random_game(5, 6)
    assert random_game(5, 6) != random_game(5, 7)


# ---------------------------------------------------------------- who may act


def all_seat_actions(state: State, seat: int) -> list[Action]:
    """Every seat action worth trying for ``seat``: all asks, calls, declarations, passes,
    choices and votes, and a few assignments."""
    actions: list[Action] = [Ask(seat, target, card) for target in SEATS for card in CARDS]
    actions += [Call(seat, s) for s in SETS] + [Declare(seat, s) for s in SETS] + [Pass(seat)]
    actions += [Choose(seat, chosen) for chosen in SEATS] + [Vote(seat, chosen) for chosen in SEATS]
    mates = team_seats(team_of(seat))
    actions += [Assign(seat, (mates[i % 3],) * 6) for i in range(3)]
    return actions


def accepted(state: State, action: Action) -> bool:
    try:
        apply(state, action)
    except IllegalActionError:
        return False
    return True


@pytest.mark.parametrize("game_seed", [3, 18])
def test_legal_actions_are_exactly_the_seat_actions_apply_accepts(game_seed: int) -> None:
    """``legal_actions`` lists every seat action the engine accepts and nothing else, in every
    phase, and ``acting_seats`` is exactly the seats with something to do. Checked at every
    state of two whole games that reach every phase; the search for unlisted actions the
    engine would accept runs at every fifth state."""
    actions = random_game(game_seed, 1_000 + game_seed)
    for index, (state, _) in enumerate(replay(game_seed, actions)):
        acting: list[int] = []
        for seat in SEATS:
            listed = legal_actions(state, seat)
            if listed:
                acting.append(seat)
            assert len(set(listed)) == len(listed)
            assignments = [a for a in listed if isinstance(a, Assign)]
            sample = [a for a in listed if not isinstance(a, Assign)] + assignments[::97]
            assert all(accepted(state, a) for a in sample)
            if index % 5 == 0:
                tried = all_seat_actions(state, seat)
                assert set(listed) >= {a for a in tried if accepted(state, a)}
        assert tuple(acting) == acting_seats(state)


def test_assignments_cover_every_teammate_combination() -> None:
    """R.4.1: each of the six cards goes to any member of the caller's team: 3^6 ways."""
    state = new_game(0)
    state, _ = apply(state, OpenWindow())
    state, _ = apply(state, Declare(4, 0))
    state, _ = apply(state, CloseWindow())
    listed = legal_actions(state, 4)
    assert len(listed) == 3**6
    assert all(isinstance(a, Assign) and set(a.holders) <= {3, 4, 5} for a in listed)


def test_nobody_acts_after_the_game_ends() -> None:
    actions = random_game(1, 2)
    *_, (state, _) = replay(1, actions)
    assert acting_seats(state) == ()
    assert all(legal_actions(state, seat) == () for seat in SEATS)


# ---------------------------------------------------------------- replay


def test_replay_matches_applying_actions_one_by_one() -> None:
    """docs/determinism.md §8: a game record is the seed plus the ordered actions."""
    actions = random_game(3, 4)
    state = new_game(3)
    for (replayed, replayed_records), action in zip(replay(3, actions), actions, strict=True):
        state, records = apply(state, action)
        assert (replayed, replayed_records) == (state, records)


def test_replay_stops_at_an_illegal_action() -> None:
    with pytest.raises(IllegalActionError):
        list(replay(3, [OpenWindow(), OpenWindow()]))


# ---------------------------------------------------------------- the action codec

EVERY_ACTION: list[Action] = [
    Ask(0, 3, 5),
    Call(1, 2),
    Declare(4, 8),
    Pass(5),
    Assign(2, (0, 1, 2, 2, 1, 0)),
    Choose(0, 1),
    Vote(3, 4),
    OpenWindow(),
    CloseWindow(),
    AssignTimeout(),
    ChoiceTimeout(),
]


@pytest.mark.parametrize("action", EVERY_ACTION, ids=lambda a: type(a).__name__)
def test_codec_round_trips_every_action(action: Action) -> None:
    data = action_to_data(action)
    assert data["type"] == type(action).__name__
    assert action_from_data(data) == action


def test_codec_writes_lists_not_tuples() -> None:
    assert action_to_data(Assign(2, (0, 1, 2, 2, 1, 0))) == {
        "type": "Assign",
        "seat": 2,
        "holders": [0, 1, 2, 2, 1, 0],
    }


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"type": "Shout"}, "unknown action type"),
        ({"seat": 0}, "unknown action type"),
        ({"type": "Pass"}, "exactly the keys"),
        ({"type": "Pass", "seat": 0, "extra": 1}, "exactly the keys"),
        ({"type": "Pass", "seat": "0"}, "must be an int"),
        ({"type": "Pass", "seat": True}, "must be an int"),
        ({"type": "Assign", "seat": 0, "holders": (0, 1, 2, 0, 1, 2)}, "list of ints"),
        ({"type": "Assign", "seat": 0, "holders": [0, 1, 2, 0, 1, "2"]}, "list of ints"),
    ],
)
def test_codec_rejects_malformed_data(data: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        action_from_data(data)
