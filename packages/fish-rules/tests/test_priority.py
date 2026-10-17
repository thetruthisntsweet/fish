"""Tests for fish_rules.priority: call priority (R.8.1) and the run-out caller (R.6.2)."""

from collections import Counter

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cards import SEATS, team_of
from fish_rules.priority import (
    first_in_priority,
    order_from_starts,
    priority_order,
    runout_caller,
)
from fish_rules.rng import stream

U64 = st.integers(min_value=0, max_value=2**64 - 1)
TEAM = st.integers(min_value=0, max_value=1)


# ---------------------------------------------------------------- R.8.1 the order


def test_r8_1_worked_example() -> None:
    """R.8.1: starting with seat 1 against seat 4 gives 1, 4, 2, 5, 0, 3."""
    assert order_from_starts(1, 4) == (1, 4, 2, 5, 0, 3)


def test_r8_1_either_team_may_go_first() -> None:
    assert order_from_starts(4, 1) == (4, 1, 5, 2, 3, 0)


def test_r8_1_wraps_within_each_team() -> None:
    assert order_from_starts(2, 5) == (2, 5, 0, 3, 1, 4)


@pytest.mark.parametrize(("first", "second"), [(0, 1), (3, 5), (4, 4)])
def test_r8_1_starts_must_be_on_different_teams(first: int, second: int) -> None:
    with pytest.raises(ValueError, match="same team"):
        order_from_starts(first, second)


@given(U64, U64)
def test_r8_1_order_alternates_teams_and_covers_every_seat(seed: int, window: int) -> None:
    """R.8.1: priority alternates between teams; every seat appears exactly once."""
    order = priority_order(seed, window)
    assert sorted(order) == list(SEATS)
    teams = [team_of(seat) for seat in order]
    assert all(teams[i] != teams[i + 1] for i in range(5))


@given(U64, U64)
def test_r8_1_moves_clockwise_within_each_team(seed: int, window: int) -> None:
    """R.8.1: within each team, the next teammate clockwise each time."""
    order = priority_order(seed, window)
    for team in (0, 1):
        members = [seat for seat in order if team_of(seat) == team]
        base = 3 * team
        assert [(seat - base) % 3 for seat in members] in ([0, 1, 2], [1, 2, 0], [2, 0, 1])


@given(U64, U64)
def test_r8_1_chosen_by_seed_and_window_index(seed: int, window: int) -> None:
    """R.8.1: the game's seed and the window's index choose the order."""
    assert priority_order(seed, window) == priority_order(seed, window)


def test_r8_1_frozen_draw_procedure() -> None:
    """docs/determinism.md §7: below(2) for the first team, then below(3) for team 0's start,
    then below(3) for team 1's start, from stream ``priority`` at the window index."""
    for window in range(100):
        rng = stream(7, "priority", window)
        first_team, start0, start1 = rng.below(2), rng.below(3), 3 + rng.below(3)
        expected = (
            order_from_starts(start0, start1)
            if first_team == 0
            else order_from_starts(start1, start0)
        )
        assert priority_order(7, window) == expected


def test_r8_1_all_eighteen_orders_occur_about_equally() -> None:
    """2 first teams x 3 starts x 3 starts = 18 orders, each with probability 1/18."""
    counts = Counter(priority_order(3, window) for window in range(18_000))
    assert len(counts) == 18
    assert all(850 <= count <= 1150 for count in counts.values())


@pytest.mark.parametrize(("seed", "window"), [(-1, 0), (2**64, 0), (0, -1), (0, 2**64)])
def test_r8_1_seed_and_window_out_of_range_rejected(seed: int, window: int) -> None:
    with pytest.raises(ValueError, match=r"game_seed|index"):
        priority_order(seed, window)


# ---------------------------------------------------------------- R.4.3 resolving a window


def test_r4_3_highest_priority_declaration_proceeds() -> None:
    """R.4.3: when the window closes, the declared call with the highest priority proceeds."""
    order = order_from_starts(1, 4)
    assert first_in_priority(order, [0, 5]) == 5
    assert first_in_priority(order, [3, 0, 2]) == 2
    assert first_in_priority(order, [1, 4, 2, 5, 0, 3]) == 1
    assert first_in_priority(order, [3]) == 3


def test_r4_3_no_declarations() -> None:
    assert first_in_priority(order_from_starts(1, 4), []) is None


def test_r4_3_declarer_must_be_a_seat() -> None:
    with pytest.raises(ValueError, match="seat"):
        first_in_priority(order_from_starts(1, 4), [6])


# ---------------------------------------------------------------- R.6.2 the run-out caller


@given(U64, U64, TEAM)
def test_r6_2_runout_caller_is_first_member_of_team_in_priority_order(
    seed: int, window: int, team: int
) -> None:
    """R.6.2: the caller is the first member of the team holding cards in the R.8.1 order."""
    caller = runout_caller(seed, window, team)
    assert team_of(caller) == team
    order = priority_order(seed, window)
    assert all(team_of(seat) != team for seat in order[: order.index(caller)])


def test_r6_2_runout_caller_changes_with_window_index() -> None:
    """R.6.2: each selection counts as a window, so successive selections use new orders."""
    assert len({runout_caller(11, window, 1) for window in range(30)}) == 3


def test_r6_2_runout_team_must_be_a_team() -> None:
    with pytest.raises(ValueError, match="team"):
        runout_caller(0, 0, 2)
