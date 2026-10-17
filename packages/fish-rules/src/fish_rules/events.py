"""Actions the engine accepts, and records of what happened (Canonical Ruleset R.2, R.4.2).

**Actions** are the inputs: a game is its seed plus the ordered list of actions applied to
it, so replaying the actions reproduces every state and record (``docs/determinism.md`` §8).
Seat actions name the seat acting. ``OpenWindow`` and ``CloseWindow`` are control actions:
the environment applies them around every event, the server only when a player presses Call
and when the 1-second window ends (R.4.2, R.8.3).

**Records** are the outputs, one or more per action, in order. Three kinds are *events* in
the sense of R.4.2 and carry an event number: an ask and its answer (``AskEvent``), a call
and its result (``CallEvent``), and an after-call choice (``ChoiceEvent``). Event numbers
count from 0 and only these three kinds advance them, so log-only records and the server's
own rows (round-trip times, rejected presses) never shift a number.

Every record is either PUBLIC (all players see it as it happens; R.2.2, R.2.3, R.8.3) or
LOG_ONLY (kept in the event log but never shown to players: discarded declarations, R.4.3;
individual votes and seed choices, R.5.2). The projection (T2.4) decides exactly what each
player is shown; this marking is the rule it starts from.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from fish_rules.cards import Card, Seat, SetId, Team
from fish_rules.state import CallSource, Outcome


class Visibility(StrEnum):
    PUBLIC = "public"
    LOG_ONLY = "log_only"


# ---------------------------------------------------------------- actions


@dataclass(frozen=True, slots=True)
class Ask:
    """R.3.2: the current player asks ``target`` for ``card``."""

    seat: Seat
    target: Seat
    card: Card


@dataclass(frozen=True, slots=True)
class Call:
    """Name a set to call without a window: the current player on their turn after a window
    closed with no declaration (R.4.2), or the selected caller during run-out (R.6.2). The
    cards are assigned next, with ``Assign``."""

    seat: Seat
    set_id: SetId


@dataclass(frozen=True, slots=True)
class Declare:
    """R.4.3: declare a call on ``set_id`` in the open window, without assigning cards."""

    seat: Seat
    set_id: SetId


@dataclass(frozen=True, slots=True)
class Pass:
    """Decline to declare in the open window. Environment only: every agent is asked in
    every window (R.8.9)."""

    seat: Seat


@dataclass(frozen=True, slots=True)
class Assign:
    """R.4.1, R.4.3: the caller assigns the six cards of the called set. ``holders[i]`` is the
    teammate assigned the set's i-th card, in card-number order."""

    seat: Seat
    holders: tuple[Seat, ...]


@dataclass(frozen=True, slots=True)
class Choose:
    """R.5.2: the caller chooses which teammate holding cards takes the turn."""

    seat: Seat
    chosen: Seat


@dataclass(frozen=True, slots=True)
class Vote:
    """R.5.2: a member of the scoring team, when it is not the caller's, votes for which of
    its players holding cards takes the turn."""

    seat: Seat
    chosen: Seat


@dataclass(frozen=True, slots=True)
class OpenWindow:
    """R.4.2: open a declaration window. The environment opens one at the start of the game
    and after every event; the website only when a player presses Call (R.8.3)."""


@dataclass(frozen=True, slots=True)
class CloseWindow:
    """R.4.3: close the open window; the declared call with the highest priority proceeds."""


type Action = Ask | Call | Declare | Pass | Assign | Choose | Vote | OpenWindow | CloseWindow
"""Every input the engine accepts."""


# ---------------------------------------------------------------- events (R.4.2), numbered


@dataclass(frozen=True, slots=True)
class AskEvent:
    """R.3.3: an ask and its answer. ``success`` is True if ``target`` held ``card``, which
    then moved to ``asker``."""

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    number: int
    asker: Seat
    target: Seat
    card: Card
    success: bool


@dataclass(frozen=True, slots=True)
class CallEvent:
    """R.4.4-R.4.5, R.2.3: a call and its result.

    ``assignment[i]`` and ``holders[i]`` are the assigned and true holders of the set's i-th
    card; the true holders are revealed to all players. ``scored_by`` is the caller's team if
    the call was correct, otherwise the other team. All six cards leave play.
    """

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    number: int
    caller: Seat
    set_id: SetId
    source: CallSource
    assignment: tuple[Seat, ...]
    holders: tuple[Seat, ...]
    correct: bool
    scored_by: Team


@dataclass(frozen=True, slots=True)
class ChoiceEvent:
    """R.5: the after-call choice. Only the outcome is public: ``team`` gave the turn to
    ``seat``."""

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    number: int
    team: Team
    seat: Seat


# ---------------------------------------------------------------- other records, not numbered


@dataclass(frozen=True, slots=True)
class WindowOpened:
    """R.4.2, R.8.3: a declaration window opened. Players see that it opened, not who opened
    it or why."""

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    index: int


@dataclass(frozen=True, slots=True)
class Declared:
    """R.4.3: ``seat`` declared a call on ``set_id`` in window ``window``. Log only: who
    declared and which set are not shown while the window is open (R.8.3)."""

    visibility: ClassVar[Visibility] = Visibility.LOG_ONLY
    window: int
    seat: Seat
    set_id: SetId


@dataclass(frozen=True, slots=True)
class WindowClosed:
    """R.4.3, R.8.3: the window closed. ``caller`` and ``set_id`` are the call that proceeds,
    shown to all players, or None if no one declared."""

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    index: int
    caller: Seat | None
    set_id: SetId | None


@dataclass(frozen=True, slots=True)
class DeclarationDiscarded:
    """R.4.3: a declaration that lost on priority. Never shown to players; recorded in the
    event log."""

    visibility: ClassVar[Visibility] = Visibility.LOG_ONLY
    window: int
    seat: Seat
    set_id: SetId


@dataclass(frozen=True, slots=True)
class RunoutCallerSelected:
    """R.6.2: the run-out caller for the selection with window index ``window``."""

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    window: int
    seat: Seat


@dataclass(frozen=True, slots=True)
class VoteCast:
    """R.5.2: an individual vote. Log only: players see only the outcome."""

    visibility: ClassVar[Visibility] = Visibility.LOG_ONLY
    call_event: int
    seat: Seat
    chosen: Seat


@dataclass(frozen=True, slots=True)
class SeedChose:
    """R.5.2: the game seed chose the seat, from ``among``, because the caller did not
    choose, no votes were cast, or the vote tied. Log only."""

    visibility: ClassVar[Visibility] = Visibility.LOG_ONLY
    call_event: int
    among: tuple[Seat, ...]
    chosen: Seat


@dataclass(frozen=True, slots=True)
class GameOver:
    """R.7, R.8.2: the game ended. ``winner`` is None for an unfinished game."""

    visibility: ClassVar[Visibility] = Visibility.PUBLIC
    outcome: Outcome
    winner: Team | None


type Event = AskEvent | CallEvent | ChoiceEvent
"""The numbered events of R.4.2."""

type Record = (
    AskEvent
    | CallEvent
    | ChoiceEvent
    | WindowOpened
    | Declared
    | WindowClosed
    | DeclarationDiscarded
    | RunoutCallerSelected
    | VoteCast
    | SeedChose
    | GameOver
)
"""Everything the engine reports."""
