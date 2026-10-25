"""Reference drivers: whole games with random legal play, under the environment's mechanics
(``random_game``) or the website's (``random_website_game``).

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

``random_website_game`` plays under website mechanics instead (R.8.3), as a corpus record
records them (docs/corpus.md §5.1): presses on any turn, each an ``OpenWindow`` followed by the
presser's ``Declare`` at the same received time, more presses inside an open window, windows
closed by the window timer, assignment and choice timeouts, and uniform legal seat actions
otherwise. It also returns each action's cause and its received and sent times, which
advance by random gaps. It exists for the corpus tests (T1.6).
"""

from typing import Final

from fish_rules.cards import SEATS, Seat, SetId, Team, set_cards, team_of, team_seats
from fish_rules.engine import acting_seats, apply, legal_actions
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


WebsiteGame = tuple[tuple[Action, ...], tuple[dict[str, object], ...], tuple[tuple[int, int], ...]]
"""A website game's actions, each action's cause, and each action's (received, sent) times."""


def random_website_game(game_seed: int, policy_seed: int, max_actions: int = 2_000) -> WebsiteGame:
    """One game under website mechanics, stopped after ``max_actions`` if it has not ended."""
    rng = SplitMix64(policy_seed)
    state = new_game(game_seed)
    actions: list[Action] = []
    causes: list[dict[str, object]] = []
    times: list[tuple[int, int]] = []
    clock = 0

    def act(action: Action, cause: dict[str, object], received: int) -> None:
        nonlocal state, clock
        state, _ = apply(state, action)
        actions.append(action)
        causes.append(cause)
        clock = max(clock, received) + rng.below(5_000)
        times.append((received, clock))

    while state.phase is not Phase.OVER and len(actions) < max_actions:
        at = clock + rng.below(3_000_000)
        match state.phase:
            case Phase.TURN if rng.below(4) == 0:
                seat = rng.choice(SEATS)
                act(OpenWindow(), {"seat": seat}, at)
                act(Declare(seat, rng.choice(state.sets_in_play())), {"seat": seat}, at)
            case Phase.WINDOW if acting_seats(state) and rng.below(3) == 0:
                seat = rng.choice(acting_seats(state))
                act(Declare(seat, rng.choice(state.sets_in_play())), {"seat": seat}, at)
            case Phase.WINDOW:
                act(CloseWindow(), {"timer": "window"}, at)
            case Phase.ASSIGN if rng.below(5) == 0:
                act(AssignTimeout(), {"timer": "assignment"}, at)
            case Phase.CHOOSE | Phase.VOTE if rng.below(5) == 0:
                act(ChoiceTimeout(), {"timer": "choice"}, at)
            case _:
                seat = rng.choice(acting_seats(state))
                act(rng.choice(legal_actions(state, seat)), {"seat": seat}, at)
    return tuple(actions), tuple(causes), tuple(times)
