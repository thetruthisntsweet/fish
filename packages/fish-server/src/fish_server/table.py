"""One website game: the engine with the website's mechanics around it (T3.1).

The engine has no clock and never opens a window by itself (R.8.6). ``Table`` adds what the
website needs, and nothing else: it decides no rule outcome, only when the engine is asked
(D23). It does no input or output either. Whoever runs it (the WebSocket game loop) passes
in every input with the server-clock time it arrived, in microseconds since the game
started, and calls ``advance`` to let timers fire; tests drive it the same way on a fake
clock.

**Presses** (R.8.3). A Call press names a set and carries the number of the last event the
player had seen. With no window open it opens one: ``OpenWindow`` and the presser's
``Declare``, applied together with the same received time. Inside an open window it is a
``Declare`` alone. Presses during a call assignment, an after-call choice or run-out are
rejected (R.8.3, R.6.2). A press is also rejected if an event the player had not seen scored
its set or moved one of its cards (R.8.7, ``fish_rules.engine.press_is_stale``); otherwise
it is taken against the current state.

**Seat actions.** On a turn, the current player may only ask: a call starts with a press,
like anyone's (R.4.3). An action sent while a window is open is discarded and the player is
told (R.8.3). During run-out the selected caller names the set with ``Call`` (R.6.2). Anything
the rules do not allow is rejected; the player is shown the current state and acts again
(R.8.7). Every rejection is a ``rejected`` row in the server log (docs/corpus.md §5.2).

**Timers** (R.8.5), all on the server clock: the window closes 1 second after the press that
opened it (R.8.3), the caller has 30 seconds to assign (R.4.3), and the after-call choice or
vote 15 seconds (R.5.2). A timer's action is recorded as received at its deadline, however
late ``advance`` is called, and every input first lets the timers due by its own arrival
fire, so actions are applied in the order things happened.

**Times.** Every action is stamped with when it was received; ``sent`` stamps the actions not
yet sent with when the updates they produced were handed to the transport (docs/corpus.md
§5.1). ``record`` writes the game as a ``fish-corpus-v1`` record, read back before it is
returned.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from fish_rules.cards import NUM_SETS, SEATS, Seat, SetId
from fish_rules.codec import action_to_data
from fish_rules.corpus import corpus_record
from fish_rules.engine import IllegalActionError, apply, legal_actions, press_is_stale
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    AssignTimeout,
    CallEvent,
    ChoiceEvent,
    ChoiceTimeout,
    CloseWindow,
    Declare,
    Event,
    OpenWindow,
    Record,
)
from fish_rules.state import Phase, State, new_game
from fish_rules.view import PlayerView, latest_event, project

SECOND_US: Final = 1_000_000

WINDOW_US: Final = 1 * SECOND_US
"""R.8.3: a declaration window lasts 1 second from the press that opened it."""

ASSIGN_US: Final = 30 * SECOND_US
"""R.4.3: the caller whose call proceeds has 30 seconds to assign the six cards."""

CHOICE_US: Final = 15 * SECOND_US
"""R.5.2: the after-call choice, or the vote, has 15 seconds."""

ILLEGAL: Final = "illegal"
STALE: Final = "stale"
MALFORMED: Final = "malformed"
"""Why an input was rejected, as the server log records it (``fish_rules.corpus``)."""


@dataclass(frozen=True, slots=True)
class Accepted:
    """The input was applied: ``actions`` engine actions (two for a press that opens a
    window, otherwise one)."""

    actions: int


@dataclass(frozen=True, slots=True)
class Rejected:
    """The input was not applied and is recorded as rejected. ``discarded`` is True for a
    seat action sent while a window was open, which the player is told about (R.8.3)."""

    reason: str
    discarded: bool = False


type Result = Accepted | Rejected


@dataclass(slots=True)
class Entry:
    """One applied action: why it was applied (``{"seat": s}`` or ``{"timer": t}``), when the
    input arrived or the timer fired, when its update was sent (None until then), and the
    records it produced."""

    action: Action
    cause: dict[str, object]
    received_us: int
    sent_us: int | None
    records: tuple[Record, ...] = field(default=())


_TIMED: Final[dict[Phase, tuple[int, Action, str]]] = {
    Phase.WINDOW: (WINDOW_US, CloseWindow(), "window"),
    Phase.ASSIGN: (ASSIGN_US, AssignTimeout(), "assignment"),
    Phase.CHOOSE: (CHOICE_US, ChoiceTimeout(), "choice"),
    Phase.VOTE: (CHOICE_US, ChoiceTimeout(), "choice"),
}
"""The phases a website timer ends: how long, the action applied, and the timer's name."""

_CONTROL: Final = (OpenWindow, CloseWindow, AssignTimeout, ChoiceTimeout)


class Table:
    """One game of six seats under website mechanics. Times are microseconds since the game
    started on the server's monotonic clock; the deal is at 0."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.state: State = new_game(seed)
        self.entries: list[Entry] = []
        self.log: list[dict[str, object]] = []
        self.last_event: Event | None = None
        self._records: list[Record] = []
        self._event_at: list[int] = []  # event number -> its position in _records
        self._since = 0  # when the current phase began
        self._now = 0  # the latest time any input or call has been given

    # ------------------------------------------------------------ what each seat may do

    def view(self, seat: Seat) -> PlayerView:
        """What ``seat`` is shown now (``fish_rules.view``)."""
        return project(self.state, seat, self.last_event)

    def actions(self, seat: Seat) -> tuple[Action, ...]:
        """The seat actions ``seat`` may send now. On a turn only asks, since a call starts
        with a press (R.4.3); none while a window is open (R.8.3); nobody passes."""
        match self.state.phase:
            case Phase.TURN:
                return tuple(a for a in legal_actions(self.state, seat) if isinstance(a, Ask))
            case Phase.WINDOW:
                return ()
            case _:
                return legal_actions(self.state, seat)

    def pressable(self, seat: Seat) -> tuple[SetId, ...]:
        """The sets ``seat`` may press Call on now: any set in play on a turn or in a window
        it has not declared in (R.8.3); none during an assignment, a choice or run-out."""
        state = self.state
        window = state.window
        if state.phase is Phase.TURN or (
            state.phase is Phase.WINDOW and window is not None and not window.responded[seat]
        ):
            return state.sets_in_play()
        return ()

    # ------------------------------------------------------------ timers

    def deadline(self) -> int | None:
        """When the running timer fires, or None if no timer is running."""
        timed = _TIMED.get(self.state.phase)
        return None if timed is None else self._since + timed[0]

    def advance(self, now: int) -> int:
        """Fire every timer due by ``now``; returns how many timer actions were applied."""
        self._tick(now)
        fired = 0
        while (due := self.deadline()) is not None and due <= now:
            _, action, timer = _TIMED[self.state.phase]
            self._apply(action, {"timer": timer}, due)
            fired += 1
        return fired

    # ------------------------------------------------------------ inputs

    def press(self, seat: Seat, set_id: int, seen: int | None, now: int) -> Result:
        """A Call press by ``seat`` naming ``set_id``, from a player whose last event seen was
        number ``seen`` (None if none), arriving at ``now``."""
        self.advance(now)
        data = {"type": "Press", "seat": seat, "set_id": set_id, "seen": seen}
        if (
            _not_int(set_id)
            or not 0 <= set_id < NUM_SETS
            or (seen is not None and (_not_int(seen) or not 0 <= seen < len(self._event_at)))
        ):
            return self._reject(seat, data, MALFORMED, now)
        if not self.pressable(seat):
            return self._reject(seat, data, ILLEGAL, now)
        newer = self._records if seen is None else self._records[self._event_at[seen] + 1 :]
        if press_is_stale(newer, set_id):
            return self._reject(seat, data, STALE, now)
        if set_id not in self.state.sets_in_play():
            return self._reject(seat, data, ILLEGAL, now)
        cause: dict[str, object] = {"seat": seat}
        if self.state.phase is Phase.TURN:
            self._apply(OpenWindow(), cause, now)
            self._apply(Declare(seat, set_id), cause, now)
            return Accepted(2)
        self._apply(Declare(seat, set_id), cause, now)
        return Accepted(1)

    def act(self, seat: Seat, action: Action, now: int) -> Result:
        """A seat action sent by ``seat``, arriving at ``now``."""
        self.advance(now)
        data = action_to_data(action)
        if isinstance(action, _CONTROL) or getattr(action, "seat", None) != seat:
            return self._reject(seat, data, MALFORMED, now)
        if self.state.phase is Phase.WINDOW:
            return self._reject(seat, data, ILLEGAL, now, discarded=True)
        if action not in self.actions(seat):
            return self._reject(seat, data, ILLEGAL, now)
        self._apply(action, {"seat": seat}, now)
        return Accepted(1)

    def reject(self, seat: Seat, data: object, reason: str, now: int) -> Rejected:
        """Record an input the transport could not even read (``malformed``)."""
        self.advance(now)
        return self._reject(seat, data, reason, now)

    def sent(self, now: int) -> int:
        """Stamp every action not yet sent as sent at ``now``; returns how many."""
        self._tick(now)
        stamped = 0
        for entry in self.entries:
            if entry.sent_us is None:
                entry.sent_us = max(now, entry.received_us)
                stamped += 1
        return stamped

    # ------------------------------------------------------------ the record

    def record(
        self, *, game: Mapping[str, object], seats: Sequence[Mapping[str, object]]
    ) -> dict[str, object]:
        """The game so far as a ``fish-corpus-v1`` record, with ``game`` and ``seats`` as the
        record writes them. Every action must have been sent."""
        if any(entry.sent_us is None for entry in self.entries):
            raise ValueError("every action must be sent before the game is recorded")
        return corpus_record(
            self.seed,
            [entry.action for entry in self.entries],
            self.state,
            game=game,
            seats=seats,
            times=[(e.received_us, e.sent_us or 0) for e in self.entries],
            causes=[entry.cause for entry in self.entries],
            log=self.log,
        )

    # ------------------------------------------------------------ inside

    def _tick(self, now: int) -> None:
        if _not_int(now) or now < self._now:
            raise ValueError(f"time never goes back: {now!r} after {self._now}")
        self._now = now

    def _apply(self, action: Action, cause: dict[str, object], received: int) -> None:
        before = self.state.phase
        try:
            self.state, records = apply(self.state, action)
        except IllegalActionError as error:  # pragma: no cover - the checks above prevent it
            raise AssertionError(f"the table let through an illegal action: {error}") from error
        self.entries.append(Entry(action, cause, received, None, records))
        for record in records:
            if isinstance(record, AskEvent | CallEvent | ChoiceEvent):
                self._event_at.append(len(self._records))
            self._records.append(record)
        self.last_event = latest_event(records, self.last_event)
        if self.state.phase is not before:
            self._since = received

    def _reject(
        self, seat: Seat, data: object, reason: str, now: int, *, discarded: bool = False
    ) -> Rejected:
        if seat not in SEATS:
            raise ValueError(f"no seat {seat!r}")
        self.log.append(
            {
                "type": "rejected",
                "after": len(self.entries),
                "at_us": now,
                "seat": seat,
                "input": data,
                "reason": reason,
            }
        )
        return Rejected(reason, discarded)


def _not_int(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int)
