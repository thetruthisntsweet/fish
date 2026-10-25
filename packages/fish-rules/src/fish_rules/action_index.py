"""Seat actions as integers, for agents (docs/determinism.md §9).

Every seat action is one integer in ``range(NUM_ACTIONS)``, read from the acting seat's point
of view, so one policy serves every seat:

======== ============================================================================
Indices  Action
======== ============================================================================
0-161    ``Ask``: 54 x opponent index + card. Opponents are the other team's seats,
         ascending, so opponent index 0, 1, 2 is seat 3, 4, 5 for team 0 and 0, 1, 2
         for team 1.
162-170  ``Call``: 162 + set
171-179  ``Declare``: 171 + set
180      ``Pass``
181-909  ``Assign``: 181 + the six holders as teammate indices, read as a base-3 number
         with the set's first card as the most significant digit. Teammates are the
         seat's own team, ascending, the seat included.
910-912  Nominate a teammate, by teammate index: ``Choose`` in the after-call choice,
         ``Vote`` in the team vote. The phase says which (R.5.2).
======== ============================================================================

FROZEN: trained agents and recorded policies depend on this layout. It is named
``fish-action-index-v1``; a different layout needs a new name. Game records do not use it;
they store actions with ``fish_rules.codec``.

``legal_indices`` and ``legal_mask`` give the indices of exactly the actions
``fish_rules.engine.legal_actions`` lists. The projection (``fish_rules.view``) carries
them, so the environment and the website build the same mask without either knowing the
layout.
"""

from typing import Final

from fish_rules.cards import (
    CARDS_PER_SET,
    NUM_CARDS,
    NUM_SETS,
    SEATS_PER_TEAM,
    Seat,
    check_card,
    check_seat,
    check_set,
    opponent_team,
    team_of,
    team_seats,
)
from fish_rules.engine import legal_actions
from fish_rules.events import Action, Ask, Assign, Call, Choose, Declare, Pass, Vote
from fish_rules.state import Phase, State

ACTION_INDEX_ENCODING: Final = "fish-action-index-v1"
"""Names this layout."""

ASK_BASE: Final = 0
CALL_BASE: Final = ASK_BASE + SEATS_PER_TEAM * NUM_CARDS
DECLARE_BASE: Final = CALL_BASE + NUM_SETS
PASS_INDEX: Final = DECLARE_BASE + NUM_SETS
ASSIGN_BASE: Final = PASS_INDEX + 1
NOMINATE_BASE: Final = ASSIGN_BASE + SEATS_PER_TEAM**CARDS_PER_SET
NUM_ACTIONS: Final = NOMINATE_BASE + SEATS_PER_TEAM
"""913: the size of the action space."""

type SeatAction = Ask | Call | Declare | Pass | Assign | Choose | Vote
"""The actions a seat takes. Control actions (windows, timeouts) have no index."""


def opponents(seat: Seat) -> tuple[Seat, Seat, Seat]:
    """``seat``'s opponents, ascending: opponent index i is ``opponents(seat)[i]``."""
    return team_seats(opponent_team(team_of(seat)))


def teammates(seat: Seat) -> tuple[Seat, Seat, Seat]:
    """``seat``'s team, ascending, ``seat`` included: teammate index i is ``teammates(seat)[i]``."""
    return team_seats(team_of(seat))


def _position(seat: Seat, among: tuple[Seat, ...], what: str) -> int:
    if check_seat(seat) not in among:
        raise ValueError(f"seat {seat} is not {what}")
    return among.index(seat)


def encode(action: Action) -> int:
    """The index of ``action``, from its own seat's point of view. Raises ValueError if the
    action has no index: a control action, an ask of a teammate, or an assignment or
    nomination outside the team. Whether the action is legal now is the engine's business."""
    match action:
        case Ask(seat=seat, target=target, card=card):
            opponent = _position(target, opponents(seat), f"an opponent of seat {seat}")
            return ASK_BASE + NUM_CARDS * opponent + check_card(card)
        case Call(set_id=set_id):
            check_seat(action.seat)
            return CALL_BASE + check_set(set_id)
        case Declare(set_id=set_id):
            check_seat(action.seat)
            return DECLARE_BASE + check_set(set_id)
        case Pass():
            check_seat(action.seat)
            return PASS_INDEX
        case Assign(seat=seat, holders=holders):
            if len(holders) != CARDS_PER_SET:
                raise ValueError(f"an assignment names six holders, got {len(holders)}")
            mates = teammates(seat)
            number = 0
            for holder in holders:
                number = SEATS_PER_TEAM * number + _position(holder, mates, f"a teammate of {seat}")
            return ASSIGN_BASE + number
        case Choose(seat=seat, chosen=chosen) | Vote(seat=seat, chosen=chosen):
            return NOMINATE_BASE + _position(chosen, teammates(seat), f"a teammate of {seat}")
        case _:
            raise ValueError(f"{type(action).__name__} is a control action and has no index")


def decode(seat: Seat, index: int, phase: Phase) -> SeatAction:
    """The action ``seat`` takes by choosing ``index`` in ``phase``. Only a nomination needs
    the phase: it is a ``Vote`` in ``Phase.VOTE`` and a ``Choose`` otherwise. Raises
    ValueError if ``index`` is out of range."""
    check_seat(seat)
    if isinstance(index, bool) or not 0 <= index < NUM_ACTIONS:
        raise ValueError(f"an action index is in range({NUM_ACTIONS}), got {index!r}")
    if index < CALL_BASE:
        opponent, card = divmod(index - ASK_BASE, NUM_CARDS)
        return Ask(seat, opponents(seat)[opponent], card)
    if index < DECLARE_BASE:
        return Call(seat, index - CALL_BASE)
    if index < PASS_INDEX:
        return Declare(seat, index - DECLARE_BASE)
    if index == PASS_INDEX:
        return Pass(seat)
    mates = teammates(seat)
    if index < NOMINATE_BASE:
        number = index - ASSIGN_BASE
        digits: list[Seat] = []
        for _ in range(CARDS_PER_SET):
            number, digit = divmod(number, SEATS_PER_TEAM)
            digits.append(mates[digit])
        return Assign(seat, tuple(reversed(digits)))
    chosen = mates[index - NOMINATE_BASE]
    return Vote(seat, chosen) if phase is Phase.VOTE else Choose(seat, chosen)


def legal_indices(state: State, seat: Seat) -> tuple[int, ...]:
    """The indices of every action ``seat`` may take now, ascending. Empty if it may not act."""
    return tuple(sorted(encode(action) for action in legal_actions(state, seat)))


def legal_mask(state: State, seat: Seat) -> bytes:
    """``NUM_ACTIONS`` bytes, 1 where ``seat`` may take that action now and 0 elsewhere."""
    mask = bytearray(NUM_ACTIONS)
    for index in legal_indices(state, seat):
        mask[index] = 1
    return bytes(mask)
