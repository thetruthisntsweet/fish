"""One website game: the engine with the website's mechanics around it (T3.1).

The engine has no clock and never opens a window by itself (R.8.6). ``Table`` adds what the
website needs, and nothing else: it decides no rule outcome, only when the engine is asked
(D23). It does no input or output either. Whoever runs it (the WebSocket game loop) passes
in every input with the server-clock time it arrived, in microseconds since the game
started, and calls ``advance`` to let timers fire; tests drive it the same way on a fake
clock. Inputs for a seat come from whoever holds it: its person, or the bot that replaced
them.

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
vote 15 seconds (R.5.2). A person whose turn it is has 60 seconds to act (R.8.4). The turn
timer pauses while a window, an assignment or a choice is in progress, and every new turn
starts a fresh one: after an ask, an after-call choice, a run-out caller's selection, and at
the deal. A timer's outcome is recorded at its deadline, however late ``advance`` is called,
and every input first lets the timers due by its own arrival fire, so things are applied in
the order they happened.

**People and bots** (R.8.4). A person who disconnects has 30 seconds to reconnect; their turn
timer keeps running. A person who does not act in time, or does not reconnect in time, is
replaced for the rest of the game by the table's ``replacement`` bot, recorded as a
``handover`` row; seats a bot held from the deal have no timers of their own. Every person
starts out waiting to connect, with the same 30 seconds. ``connection`` rows record
``connected``, ``disconnected`` and ``reconnected`` (docs/corpus.md §4.1, §5.2).

**Times.** Every action is stamped with when it was received; ``sent`` stamps the actions not
yet sent with when the updates they produced were handed to the transport (docs/corpus.md
§5.1). ``record`` writes the game as a ``fish-corpus-v1`` record, read back before it is
returned.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from fish_agents.memory import MemorySetting
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

TURN_US: Final = 60 * SECOND_US
"""R.8.4: the current player has 60 seconds to act."""

RECONNECT_US: Final = 30 * SECOND_US
"""R.8.4: a player who disconnects has 30 seconds to reconnect."""

ILLEGAL: Final = "illegal"
STALE: Final = "stale"
MALFORMED: Final = "malformed"
"""Why an input was rejected, as the server log records it (``fish_rules.corpus``)."""

TURN_TIMEOUT: Final = "turn_timeout"
DISCONNECT: Final = "disconnect"
"""Why a seat was handed to a bot (R.8.4)."""


@dataclass(frozen=True, slots=True)
class Controller:
    """A bot: its agent version, as the corpus records it (``b1-v1``), and its memory."""

    agent: str
    memory: MemorySetting


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

_TURNS: Final = (Phase.TURN, Phase.RUNOUT)
"""The phases in which a seat has the turn, and the turn timer runs (R.8.4, R.6.2)."""

_CONTROL: Final = (OpenWindow, CloseWindow, AssignTimeout, ChoiceTimeout)


class Table:
    """One game of six seats under website mechanics. Times are microseconds since the game
    started on the server's monotonic clock; the deal is at 0.

    ``people`` are the seats people hold at the deal (the others are bots from the start);
    ``replacement`` is the bot that takes over a person's seat (R.8.4)."""

    def __init__(self, seed: int, *, people: Collection[Seat], replacement: Controller) -> None:
        if not people or any(seat not in SEATS for seat in people):
            raise ValueError(f"people are one or more seats, not {sorted(people)!r}")
        self.seed = seed
        self.replacement = replacement
        self.state: State = new_game(seed)
        self.entries: list[Entry] = []
        self.log: list[dict[str, object]] = []
        self.last_event: Event | None = None
        self.seated: frozenset[Seat] = frozenset(people)
        """Seats people held at the deal."""
        self.people: frozenset[Seat] = self.seated
        """Seats a person holds now: those at the deal, less any handed to a bot."""
        self._records: list[Record] = []
        self._event_at: list[int] = []  # event number -> its position in _records
        self._since = 0  # when the current phase began
        self._now = 0  # the latest time any input or call has been given
        self._connected: set[Seat] = set()
        self._ever: set[Seat] = set()  # seats whose person has connected at least once
        self._away: dict[Seat, int] = dict.fromkeys(self.people, RECONNECT_US)  # deadline
        self._turn_at: int | None = None  # when the running turn timer fires
        self._turn(0)

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

    def connected(self, seat: Seat) -> bool:
        """Whether the person holding ``seat`` is connected now."""
        return seat in self._connected

    # ------------------------------------------------------------ timers

    def turn_deadline(self) -> int | None:
        """When the running turn timer fires, or None if none is running (R.8.4)."""
        return self._turn_at

    def deadline(self) -> int | None:
        """When the next timer of any kind fires, or None if none is running."""
        due = self._next()
        return None if due is None else due[0]

    def advance(self, now: int) -> int:
        """Fire every timer due by ``now``, in the order they fall due; returns how many fired:
        timer actions and handovers."""
        self._tick(now)
        fired = 0
        while (due := self._next()) is not None and due[0] <= now:
            at, kind, seat = due
            if kind == 0:
                _, action, timer = _TIMED[self.state.phase]
                self._apply(action, {"timer": timer}, at)
            else:
                self._hand_over(seat, TURN_TIMEOUT if kind == 1 else DISCONNECT, at)
            fired += 1
        return fired

    # ------------------------------------------------------------ connections (R.8.4)

    def connect(self, seat: Seat, now: int) -> bool:
        """The person holding ``seat`` connected, or reconnected after a disconnect, at
        ``now``. False (and nothing recorded) if no person holds the seat any more, or they
        are connected already."""
        self.advance(now)
        if seat not in self.people or seat in self._connected:
            return False
        state = "connected" if seat not in self._ever else "reconnected"
        self._connected.add(seat)
        self._ever.add(seat)
        self._away.pop(seat, None)
        self._row("connection", seat, now, state=state)
        return True

    def disconnect(self, seat: Seat, now: int) -> bool:
        """The person holding ``seat`` lost their connection at ``now``; they have 30 seconds
        to reconnect. False (and nothing recorded) if they were not connected."""
        self.advance(now)
        if seat not in self._connected:
            return False
        self._connected.discard(seat)
        if seat in self.people and self.state.phase is not Phase.OVER:
            self._away[seat] = now + RECONNECT_US
        self._row("connection", seat, now, state="disconnected")
        return True

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

    def _next(self) -> tuple[int, int, Seat] | None:
        """The next timer to fire: when, which kind (0 the phase's timer, 1 the turn timer,
        2 a reconnection), and the seat (0 for the phase's timer). Ties go in that order."""
        if self.state.phase is Phase.OVER:
            return None
        due: list[tuple[int, int, Seat]] = []
        timed = _TIMED.get(self.state.phase)
        if timed is not None:
            due.append((self._since + timed[0], 0, 0))
        if self._turn_at is not None and self.state.current is not None:
            due.append((self._turn_at, 1, self.state.current))
        due.extend((at, 2, seat) for seat, at in self._away.items())
        return min(due, default=None)

    def _turn(self, at: int) -> None:
        """Start or stop the turn timer after a change at ``at`` (R.8.4). It runs only while a
        person has the turn, and every action after which a seat has the turn begins a new
        one (an ask, an after-call choice, a run-out caller's selection), so it starts afresh.
        A window, an assignment or a choice stops it; on the website each of them ends in a
        new turn (a window opens only with a declaration, so a call always follows), so the
        pause R.8.4 describes never needs resuming."""
        state = self.state
        in_turn = state.phase in _TURNS and state.current in self.people
        self._turn_at = at + TURN_US if in_turn else None

    def _hand_over(self, seat: Seat, reason: str, at: int) -> None:
        """R.8.4: ``seat`` goes to the replacement bot for the rest of the game."""
        self.people -= {seat}
        self._away.pop(seat, None)
        self._connected.discard(seat)
        if seat == self.state.current:
            self._turn_at = None
        bot = self.replacement
        self._row("handover", seat, at, reason=reason, agent=bot.agent, **bot.memory.as_corpus())

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
        self._turn(received)
        if self.state.phase is Phase.OVER:
            self._away.clear()

    def _row(self, kind: str, seat: Seat, at: int, **fields: object) -> None:
        row: dict[str, object] = {"type": kind, "after": len(self.entries), "at_us": at}
        self.log.append(row | {"seat": seat} | fields)

    def _reject(
        self, seat: Seat, data: object, reason: str, now: int, *, discarded: bool = False
    ) -> Rejected:
        if seat not in SEATS:
            raise ValueError(f"no seat {seat!r}")
        self._row("rejected", seat, now, input=data, reason=reason)
        return Rejected(reason, discarded)


def _not_int(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int)
