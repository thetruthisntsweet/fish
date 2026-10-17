"""Call priority in a declaration window (Canonical Ruleset R.8.1) and the run-out caller (R.6.2).

FROZEN: the draws below are part of every recorded game. Replaying a game must give the same
priority order in every window, so changing the number, order or meaning of the draws breaks
replay of existing games and requires a new ruleset version (R.10). Specified in
``docs/determinism.md`` §7; checked by ``tests/vectors/priority_v1.json`` and the independent
JavaScript implementation.
"""

from collections.abc import Iterable

from fish_rules.cards import (
    NUM_TEAMS,
    SEATS_PER_TEAM,
    Seat,
    Team,
    check_seat,
    check_team,
    next_teammate,
    team_of,
)
from fish_rules.rng import stream

type PriorityOrder = tuple[Seat, Seat, Seat, Seat, Seat, Seat]
"""All six seats, highest priority first."""


def order_from_starts(first: Seat, second: Seat) -> PriorityOrder:
    """R.8.1: the priority order that starts with ``first`` against ``second``.

    ``first`` and ``second`` must be on different teams. Priority alternates team by team,
    moving to the next teammate clockwise within each team each time: starting with seat 1
    against seat 4 gives 1, 4, 2, 5, 0, 3.
    """
    if team_of(first) == team_of(second):
        raise ValueError(f"seats {first} and {second} are on the same team")
    a, b = first, second
    order: list[Seat] = []
    for _ in range(SEATS_PER_TEAM):
        order += (a, b)
        a, b = next_teammate(a), next_teammate(b)
    return (order[0], order[1], order[2], order[3], order[4], order[5])


def priority_order(game_seed: int, window_index: int) -> PriorityOrder:
    """R.8.1: the priority order of the declaration window with index ``window_index``.

    A window's index is the number of declaration windows opened earlier in the same game,
    starting from 0; run-out selections count as windows (R.6.2).

    FROZEN: three draws from stream ``priority`` with index ``window_index``, always all
    three and always in this order:

    1. ``below(2)``: the team that goes first;
    2. ``below(3)``: the starting player of team 0 (seat 0, 1 or 2);
    3. ``below(3)``: the starting player of team 1 (seat 3, 4 or 5, as 3 + the draw).
    """
    rng = stream(game_seed, "priority", window_index)
    first_team = rng.below(NUM_TEAMS)
    starts = (rng.below(SEATS_PER_TEAM), SEATS_PER_TEAM + rng.below(SEATS_PER_TEAM))
    return order_from_starts(starts[first_team], starts[1 - first_team])


def first_in_priority(order: PriorityOrder, seats: Iterable[Seat]) -> Seat | None:
    """R.4.3, R.8.1: the seat in ``seats`` that comes earliest in ``order``, or None if empty.

    Used to pick which declared call proceeds when a window closes.
    """
    candidates = {check_seat(seat) for seat in seats}
    return next((seat for seat in order if seat in candidates), None)


def runout_caller(game_seed: int, window_index: int, team: Team) -> Seat:
    """R.6.2: the caller during run-out is the first member of ``team`` in the R.8.1 priority
    order of the window with index ``window_index``. The member need not hold cards."""
    check_team(team)
    order = priority_order(game_seed, window_index)
    return next(seat for seat in order if team_of(seat) == team)
