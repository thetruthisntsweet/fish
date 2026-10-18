"""A reference driver: whole games under the environment's mechanics, with random legal play.

``random_game`` applies the environment's protocol around the engine: a declaration window at
the start of the game and after every event, before the current player acts (R.4.2), with
every seat asked to declare or pass in every window (R.8.9). Every choice is drawn from a
generator seeded by ``policy_seed``, so a (game seed, policy seed) pair always gives the same
game. It exists for the golden replays and the whole-game invariant tests (T2.2, T2.5); the
PettingZoo environment (T2.3) and the B0 agent (T5.1) supersede it for anything else.

The policy is legal but not uniform. A seat whose team holds every card of a set in play
declares it 1 time in 4 (half the time on its own turn), so correct calls, and the caller's
after-call choice, are common; otherwise declarations are rare (1 in 100 responses) and asks
are preferred to calls (24 in 25). Half of all assignments use the true holders where they are
on the caller's team. That keeps games short and makes run-out, ties, votes and discarded
declarations common enough to test. It reads hidden state, which no agent may do.
"""

from typing import Final

from fish_rules.cards import Seat, SetId, Team, set_cards, team_of, team_seats
from fish_rules.engine import acting_seats, apply, legal_actions
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    Assign,
    Call,
    CallEvent,
    ChoiceEvent,
    Choose,
    CloseWindow,
    Declare,
    OpenWindow,
    Pass,
    Vote,
)
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase, State, new_game

COMPLETE_ODDS: Final = 4
"""A seat whose team holds a whole set declares it in one window response in this many."""

DECLARE_ODDS: Final = 100
"""Otherwise, one response in this many is a declaration of a random set."""

CALL_ODDS: Final = 25
"""On a turn with asks available, one in this many is a call instead."""


def _complete_sets(state: State, team: Team) -> tuple[SetId, ...]:
    """Sets in play whose six cards are all held by ``team``: a call on one can be correct."""
    return tuple(
        set_id
        for set_id in state.sets_in_play()
        if all(state.holder(card) in team_seats(team) for card in set_cards(set_id))
    )


def _response(state: State, seat: Seat, rng: SplitMix64) -> Declare | Pass:
    """A window response: often a set the seat's team holds whole, rarely any set, else pass."""
    complete = _complete_sets(state, team_of(seat))
    if complete and rng.below(COMPLETE_ODDS) == 0:
        return Declare(seat, rng.choice(complete))
    if rng.below(DECLARE_ODDS) == 0:
        return Declare(seat, rng.choice(state.sets_in_play()))
    return Pass(seat)


def _turn(state: State, seat: Seat, rng: SplitMix64) -> Action:
    """A turn: half the time a set the team holds whole, if any; else mostly an ask."""
    complete = _complete_sets(state, team_of(seat))
    if complete and rng.below(2) == 0:
        return Call(seat, rng.choice(complete))
    options = legal_actions(state, seat)
    asks = [a for a in options if isinstance(a, Ask)]
    calls = [a for a in options if isinstance(a, Call)]
    return rng.choice(asks if asks and rng.below(CALL_ODDS) else calls)


def _assignment(state: State, rng: SplitMix64) -> Assign:
    """Half the time the true holders where they are on the caller's team (often correct);
    otherwise a random assignment to teammates (usually incorrect)."""
    call = state.call
    assert call is not None
    mates = team_seats(team_of(call.caller))
    informed = rng.below(2) == 0
    holders: list[Seat] = []
    for card in set_cards(call.set_id):
        holder = state.holder(card)
        holders.append(holder if informed and holder in mates else rng.choice(mates))
    return Assign(call.caller, tuple(holders))


def random_game(game_seed: int, policy_seed: int) -> tuple[Action, ...]:
    """The actions of one complete game under environment mechanics (R.4.2, R.8.6, R.8.9)."""
    rng = SplitMix64(policy_seed)
    state = new_game(game_seed)
    actions: list[Action] = []
    window_due = True

    def act(action: Action) -> None:
        nonlocal state, window_due
        state, records = apply(state, action)
        actions.append(action)
        if any(isinstance(r, AskEvent | CallEvent | ChoiceEvent) for r in records):
            window_due = True

    while state.phase is not Phase.OVER:
        match state.phase:
            case Phase.TURN if window_due:
                window_due = False
                act(OpenWindow())
            case Phase.TURN:
                act(_turn(state, acting_seats(state)[0], rng))
            case Phase.WINDOW:
                for seat in acting_seats(state):
                    act(_response(state, seat, rng))
                act(CloseWindow())
            case Phase.ASSIGN:
                act(_assignment(state, rng))
            case Phase.CHOOSE:
                (seat,) = acting_seats(state)
                assert state.choice is not None
                act(Choose(seat, rng.choice(state.choice.candidates)))
            case Phase.VOTE:
                for seat in acting_seats(state):
                    assert state.choice is not None
                    act(Vote(seat, rng.choice(state.choice.candidates)))
            case _:
                (seat,) = acting_seats(state)
                act(Call(seat, rng.choice(state.sets_in_play())))
    return tuple(actions)
