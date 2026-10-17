"""Tests for fish_rules.state: the starting state, derived values, consistency and hashing."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cards import NUM_SETS, SEATS, deal, first_player, set_cards, team_seats
from fish_rules.state import (
    MAX_ASKS,
    SETS_TO_WIN,
    STATE_ENCODING,
    CallSource,
    Outcome,
    PendingCall,
    PendingChoice,
    Phase,
    State,
    Window,
    canonical,
    check_consistency,
    new_game,
    state_hash,
)

U64 = st.integers(min_value=0, max_value=2**64 - 1)


def scored(state: State, set_id: int, team: int) -> State:
    """``state`` with ``set_id`` scored by ``team`` and its cards removed from every hand."""
    gone = set(set_cards(set_id))
    hands = tuple(tuple(card for card in hand if card not in gone) for hand in state.hands)
    by = list(state.scored_by)
    by[set_id] = team
    return replace(state, hands=hands, scored_by=tuple(by))


def empty_window(index: int = 0) -> Window:
    return Window(index=index, declared=(None,) * 6, responded=(False,) * 6)


def a_choice() -> PendingChoice:
    return PendingChoice(
        team=0, candidates=(0, 1), chooser=None, votes=(None, None, None), call_event=3
    )


# ---------------------------------------------------------------- R.1.4 the starting state


@given(U64)
def test_r1_4_new_game_deals_from_the_seed(seed: int) -> None:
    """R.1.4: the deal and the seat of the first turn come from the seed."""
    state = new_game(seed)
    assert state.hands == deal(seed)
    assert state.current == first_player(seed)
    assert state.phase is Phase.TURN
    assert state.scored_by == (None,) * NUM_SETS
    assert (state.windows_opened, state.events, state.asks) == (0, 0, 0)
    assert (state.window, state.call, state.choice, state.outcome) == (None, None, None, None)
    check_consistency(state)


def test_constants() -> None:
    """R.7.1: five sets win; R.8.2: 1,000 asks end the game as unfinished."""
    assert SETS_TO_WIN == 5
    assert MAX_ASKS == 1_000


def test_state_is_immutable() -> None:
    state = new_game(1)
    with pytest.raises(FrozenInstanceError):
        state.phase = Phase.OVER  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------- R.2 public and hidden values


def test_r2_2_hand_sizes_and_score() -> None:
    """R.2.2: hand sizes and the score are public values derived from the state."""
    state = new_game(5)
    assert [state.hand_size(seat) for seat in SEATS] == [9] * 6
    assert (state.score(0), state.score(1)) == (0, 0)
    state = scored(scored(scored(state, 0, 0), 4, 1), 8, 0)
    assert (state.score(0), state.score(1)) == (2, 1)
    assert sum(state.hand_size(seat) for seat in SEATS) == 54 - 18
    assert state.sets_in_play() == (1, 2, 3, 5, 6, 7)
    check_consistency(state)


def test_r2_1_holder_is_the_true_holder() -> None:
    """R.2.1: each card's true holder is known to the engine; none once its set is scored."""
    state = new_game(9)
    for seat in SEATS:
        for card in state.hands[seat]:
            assert state.holder(card) == seat
    state = scored(state, 2, 1)
    assert all(state.holder(card) is None for card in set_cards(2))


def test_r7_1_winner_at_five_sets() -> None:
    """R.7.1: the game ends when a team claims five or more sets."""
    state = new_game(2)
    for set_id in range(4):
        state = scored(state, set_id, 1)
    assert state.winner() is None
    assert scored(state, 4, 1).winner() == 1
    assert scored(scored(state, 4, 0), 5, 0).winner() is None


def test_r6_2_team_has_cards() -> None:
    """R.6.2: whether a team holds any cards decides when run-out starts."""
    state = new_game(3)
    assert state.team_has_cards(0)
    assert state.team_has_cards(1)
    hands = tuple(() if seat in team_seats(1) else hand for seat, hand in enumerate(state.hands))
    assert not replace(state, hands=hands).team_has_cards(1)


# ---------------------------------------------------------------- R.9 consistency


def test_r9_consistent_states_pass() -> None:
    state = new_game(4)
    check_consistency(replace(state, phase=Phase.WINDOW, window=empty_window()))
    check_consistency(replace(state, phase=Phase.ASSIGN, call=PendingCall(2, 3, CallSource.WINDOW)))
    check_consistency(replace(state, phase=Phase.VOTE, choice=a_choice(), current=None))
    check_consistency(replace(state, phase=Phase.CHOOSE, choice=a_choice(), current=None))
    check_consistency(replace(state, phase=Phase.RUNOUT))
    check_consistency(replace(state, phase=Phase.OVER, outcome=Outcome.UNFINISHED, current=None))


def _moved_card(state: State) -> State:
    """A card copied into a second hand: not conserved."""
    hands = list(state.hands)
    hands[1] = tuple(sorted({*hands[1], hands[0][0]}))
    return replace(state, hands=tuple(hands))


def _lost_card(state: State) -> State:
    hands = list(state.hands)
    hands[0] = hands[0][1:]
    return replace(state, hands=tuple(hands))


BREAKERS: list[tuple[Callable[[State], State], str]] = [
    (lambda s: replace(s, hands=s.hands[:5]), "wrong number"),
    (lambda s: replace(s, scored_by=s.scored_by[:8]), "wrong number"),
    (lambda s: replace(s, hands=(s.hands[0][::-1], *s.hands[1:])), "not sorted"),
    (_moved_card, "cards conserved"),
    (_lost_card, "cards conserved"),
    (lambda s: replace(s, scored_by=(0, *s.scored_by[1:])), "cards conserved"),
    (lambda s: replace(s, asks=-1), "negative"),
    (lambda s: replace(s, phase=Phase.WINDOW), "does not match"),
    (lambda s: replace(s, window=empty_window()), "does not match"),
    (lambda s: replace(s, phase=Phase.ASSIGN), "does not match"),
    (lambda s: replace(s, phase=Phase.VOTE), "does not match"),
    (lambda s: replace(s, phase=Phase.OVER), "outcome"),
    (lambda s: replace(s, outcome=Outcome.FINISHED), "outcome"),
    (lambda s: replace(s, current=None), "current player"),
    (lambda s: replace(s, phase=Phase.RUNOUT, current=None), "current player"),
]


@pytest.mark.parametrize(("break_it", "message"), BREAKERS)
def test_r9_inconsistent_states_rejected(break_it: Callable[[State], State], message: str) -> None:
    """R.9: cards are conserved (54 in hands plus scored sets), and the phase is coherent."""
    with pytest.raises(ValueError, match=message):
        check_consistency(break_it(new_game(6)))


# ---------------------------------------------------------------- canonical encoding and hash


def test_canonical_is_plain_json() -> None:
    state = replace(new_game(2**64 - 1), phase=Phase.WINDOW, window=empty_window(4))
    encoded = canonical(state)
    assert json.loads(json.dumps(encoded)) == encoded
    assert encoded["encoding"] == STATE_ENCODING
    assert encoded["seed"] == str(2**64 - 1)


def test_hash_of_starting_state_is_frozen() -> None:
    """Golden replays store these hashes. If this fails, the canonical encoding changed:
    change STATE_ENCODING and regenerate the golden replays, or undo the change."""
    assert state_hash(new_game(42)) == (
        "1e501687ae5a3a86fd7f40c1ad6471954a4a304febc6e3f3ff8216450dc51516"
    )


@given(U64)
def test_hash_is_a_function_of_the_state(seed: int) -> None:
    assert state_hash(new_game(seed)) == state_hash(new_game(seed))
    assert len(state_hash(new_game(seed))) == 64


def test_hash_differs_between_seeds() -> None:
    assert len({state_hash(new_game(seed)) for seed in range(100)}) == 100


def test_every_field_changes_the_hash() -> None:
    """Each part of the state is in the encoding, so no two different states share a hash
    by construction."""
    base = new_game(7)
    variants = [
        replace(base, seed=8),
        _moved_card(base),
        scored(base, 0, 0),
        scored(base, 0, 1),
        replace(base, phase=Phase.RUNOUT),
        replace(base, current=(first_player(7) + 1) % 6),
        replace(base, windows_opened=1),
        replace(base, events=1),
        replace(base, asks=1),
        replace(base, window=empty_window(0)),
        replace(base, window=empty_window(1)),
        replace(base, window=Window(0, (3, *(None,) * 5), (True, *(False,) * 5))),
        replace(base, window=Window(0, (None,) * 6, (True, *(False,) * 5))),
        replace(base, call=PendingCall(1, 2, CallSource.WINDOW)),
        replace(base, call=PendingCall(1, 2, CallSource.TURN)),
        replace(base, call=PendingCall(1, 3, CallSource.TURN)),
        replace(base, call=PendingCall(2, 3, CallSource.TURN)),
        replace(base, choice=a_choice()),
        replace(base, choice=replace(a_choice(), team=1)),
        replace(base, choice=replace(a_choice(), candidates=(0,))),
        replace(base, choice=replace(a_choice(), chooser=0)),
        replace(base, choice=replace(a_choice(), votes=(1, None, None))),
        replace(base, choice=replace(a_choice(), call_event=4)),
        replace(base, outcome=Outcome.FINISHED),
        replace(base, outcome=Outcome.UNFINISHED),
    ]
    hashes = [state_hash(state) for state in (base, *variants)]
    assert len(set(hashes)) == len(hashes)


@pytest.mark.parametrize("hash_seed", ["0", "1", "4242"])
def test_hash_does_not_depend_on_python_hash_seed(hash_seed: str) -> None:
    """Implementation Environment §6: no result may depend on set or dict iteration order."""
    code = "from fish_rules.state import new_game, state_hash; print(state_hash(new_game(42)))"
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == state_hash(new_game(42))
