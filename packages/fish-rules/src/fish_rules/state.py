"""Game state (Canonical Ruleset R.1-R.7), its consistency check and its hash.

A ``State`` is immutable: the engine (``fish_rules.engine``) returns a new state for every
action. Nothing here reads a clock or draws a random number except ``new_game``, which deals
from the seed (R.1.4). Everything the engine needs to continue a game is in the state; what
happened along the way is in the event records (``fish_rules.events``).
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fish_rules.cards import (
    NUM_SEATS,
    NUM_SETS,
    SEATS,
    SETS,
    TEAMS,
    Card,
    Hand,
    Seat,
    SetId,
    Team,
    deal,
    first_player,
    set_cards,
    team_seats,
)

SETS_TO_WIN: Final = 5
"""R.7.1: the game ends when a team claims five or more sets."""

MAX_ASKS: Final = 1_000
"""R.8.2: the engine ends any game that reaches 1,000 asks as unfinished."""

STATE_ENCODING: Final = "fish-state-v1"
"""Names the canonical encoding hashed by ``state_hash``. State hashes are not part of a game
record (a record is a seed plus an event log), so this may change, but only together with
regenerating the golden replays that store hashes."""


class Phase(StrEnum):
    """What the game is waiting for."""

    TURN = "turn"
    """R.3.1: the current player must ask or call. A window may be opened first (R.4.2)."""
    WINDOW = "window"
    """R.4.2: a declaration window is open; players declare calls (or pass, in the
    environment)."""
    ASSIGN = "assign"
    """R.4.3: the caller whose call proceeds assigns the six cards of the named set."""
    CHOOSE = "choose"
    """R.5.2: the caller chooses which teammate holding cards takes the turn."""
    VOTE = "vote"
    """R.5.2: the other team votes on which of its players holding cards takes the turn."""
    RUNOUT = "runout"
    """R.6.2: the selected caller of the team holding cards names the next set."""
    OVER = "over"
    """R.7, R.8.2: the game has ended."""


class CallSource(StrEnum):
    """How a call reached the assignment step (R.4.2, R.4.3, R.6.2)."""

    WINDOW = "window"
    """Declared in a declaration window and chosen by priority (R.4.3, R.8.1)."""
    TURN = "turn"
    """Made by the current player on their turn, after a window closed with no declaration
    (R.4.2)."""
    RUNOUT = "runout"
    """Made by the selected caller during run-out (R.6.2)."""


class Outcome(StrEnum):
    """How a game ended."""

    FINISHED = "finished"
    """R.7.1: a team claimed five or more sets."""
    UNFINISHED = "unfinished"
    """R.8.2: the game reached 1,000 asks. Excluded from all analysis."""


@dataclass(frozen=True, slots=True)
class Window:
    """An open declaration window (R.4.2, R.4.3).

    ``declared[seat]`` is the set that seat declared, or None. ``responded[seat]`` is True once
    the seat has declared or passed. In the environment every seat responds in every window
    (R.8.9); on the website only declarers do.
    """

    index: int
    declared: tuple[SetId | None, ...]
    responded: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class PendingCall:
    """A call that has proceeded to the assignment step (R.4.3)."""

    caller: Seat
    set_id: SetId
    source: CallSource


@dataclass(frozen=True, slots=True)
class PendingChoice:
    """An after-call choice in progress (R.5).

    ``candidates``: the scoring team's players holding cards, ascending (R.5.1).
    ``chooser``: the caller if the caller's team scored, else None (the team votes) (R.5.2).
    ``votes``: one entry per member of the scoring team, in seat order; None until cast.
    ``call_event``: the event number of the call, which is the index of the ``tiebreak``
    stream used if the seed has to choose (R.5.2; ``docs/determinism.md`` §8).
    """

    team: Team
    candidates: tuple[Seat, ...]
    chooser: Seat | None
    votes: tuple[Seat | None, Seat | None, Seat | None]
    call_event: int


@dataclass(frozen=True, slots=True)
class State:
    """Everything needed to continue a game.

    ``hands``: each seat's cards, sorted ascending.
    ``scored_by``: for each set, the team that scored it, or None while it is in play.
    ``current``: in TURN, the current player; in RUNOUT, the selected caller. In WINDOW and
    ASSIGN, the current player the window or call interrupted, if any. None after a call
    until the after-call choice sets it, and at the end of the game.
    ``windows_opened``: windows opened so far, which is the index of the next one (R.8.1).
    ``events``: R.4.2 events so far (asks, calls, after-call choices), which is the number of
    the next one (``docs/determinism.md`` §8).
    ``asks``: asks so far (R.8.2).
    """

    seed: int
    hands: tuple[Hand, ...]
    scored_by: tuple[Team | None, ...]
    phase: Phase
    current: Seat | None
    windows_opened: int = 0
    events: int = 0
    asks: int = 0
    window: Window | None = None
    call: PendingCall | None = None
    choice: PendingChoice | None = None
    outcome: Outcome | None = None

    # ------------------------------------------------------------ public (R.2.2)

    def hand_size(self, seat: Seat) -> int:
        """R.2.2: every player's hand size is public."""
        return len(self.hands[seat])

    def score(self, team: Team) -> int:
        """R.2.2: the number of sets ``team`` has scored."""
        return sum(1 for scorer in self.scored_by if scorer == team)

    def sets_in_play(self) -> tuple[SetId, ...]:
        """Sets not yet scored, ascending (R.4.6)."""
        return tuple(set_id for set_id in SETS if self.scored_by[set_id] is None)

    def team_has_cards(self, team: Team) -> bool:
        """R.6.2: whether any member of ``team`` holds a card."""
        return any(self.hands[seat] for seat in team_seats(team))

    def winner(self) -> Team | None:
        """R.7.1: the team with five or more sets, if any. With nine sets there is at most
        one."""
        return next((team for team in TEAMS if self.score(team) >= SETS_TO_WIN), None)

    # ------------------------------------------------------------ hidden (R.2.1)

    def holder(self, card: Card) -> Seat | None:
        """The seat holding ``card``, or None if its set has been scored.

        Hidden information (R.2.1): only the engine, the event log and ground-truth scoring may
        use it, never an observation.
        """
        return next((seat for seat in SEATS if card in self.hands[seat]), None)


def new_game(game_seed: int) -> State:
    """R.1.4: the starting state for ``game_seed``: the deal and the first player's turn.

    No window is open yet. In the environment one opens at once (R.4.2); on the website one
    opens only when a player presses Call (R.8.3).
    """
    return State(
        seed=game_seed,
        hands=deal(game_seed),
        scored_by=(None,) * NUM_SETS,
        phase=Phase.TURN,
        current=first_player(game_seed),
    )


# ---------------------------------------------------------------- consistency (R.9)

_PENDING_BY_PHASE: Final[dict[Phase, tuple[bool, bool, bool]]] = {
    Phase.WINDOW: (True, False, False),
    Phase.ASSIGN: (False, True, False),
    Phase.CHOOSE: (False, False, True),
    Phase.VOTE: (False, False, True),
}


def check_consistency(state: State) -> None:
    """R.9: raise ValueError if ``state`` breaks a rule-level invariant.

    Cards are conserved: every card of a set in play is in exactly one hand, no card of a
    scored set is in any hand, so cards in hands plus cards in scored sets total 54. Hands are
    sorted. Counters are not negative. The phase and its pending window, call or choice agree.
    Used by tests and the nightly run; the engine does not call it.
    """
    if len(state.hands) != NUM_SEATS or len(state.scored_by) != NUM_SETS:
        raise ValueError("wrong number of hands or sets")
    for seat in SEATS:
        hand = state.hands[seat]
        if list(hand) != sorted(set(hand)):
            raise ValueError(f"hand {seat} is not sorted without duplicates")
    held = sorted(card for hand in state.hands for card in hand)
    in_play = sorted(card for set_id in state.sets_in_play() for card in set_cards(set_id))
    if held != in_play:
        raise ValueError("cards in hands do not match the sets in play (R.9: cards conserved)")
    if min(state.windows_opened, state.events, state.asks) < 0:
        raise ValueError("a counter is negative")
    expected = _PENDING_BY_PHASE.get(state.phase, (False, False, False))
    present = (state.window is not None, state.call is not None, state.choice is not None)
    if present != expected:
        raise ValueError(f"phase {state.phase} does not match its pending window, call or choice")
    if (state.phase is Phase.OVER) != (state.outcome is not None):
        raise ValueError("the outcome must be set exactly when the game is over")
    if state.phase in (Phase.TURN, Phase.RUNOUT) and state.current is None:
        raise ValueError(f"phase {state.phase} needs a current player")


# ---------------------------------------------------------------- canonical encoding and hash


def canonical(state: State) -> dict[str, object]:
    """A plain-data encoding of ``state`` with fixed keys, independent of field order.

    Only lists, dicts with string keys, ints, strings, bools and None, so it serialises the
    same way everywhere. The seed is a decimal string so that languages without big integers
    read it exactly.
    """
    window, call, choice = state.window, state.call, state.choice
    return {
        "encoding": STATE_ENCODING,
        "seed": str(state.seed),
        "hands": [list(hand) for hand in state.hands],
        "scored_by": list(state.scored_by),
        "phase": state.phase.value,
        "current": state.current,
        "windows_opened": state.windows_opened,
        "events": state.events,
        "asks": state.asks,
        "window": None
        if window is None
        else {
            "index": window.index,
            "declared": list(window.declared),
            "responded": list(window.responded),
        },
        "call": None
        if call is None
        else {"caller": call.caller, "set": call.set_id, "source": call.source.value},
        "choice": None
        if choice is None
        else {
            "team": choice.team,
            "candidates": list(choice.candidates),
            "chooser": choice.chooser,
            "votes": list(choice.votes),
            "call_event": choice.call_event,
        },
        "outcome": None if state.outcome is None else state.outcome.value,
    }


def state_hash(state: State) -> str:
    """SHA-256 (hex) of the canonical encoding written as compact JSON with sorted keys.

    Golden replays compare this after every action (Implementation Environment §6, §9).
    """
    text = json.dumps(canonical(state), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
