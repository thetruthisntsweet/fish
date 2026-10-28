"""One game in progress: the table, and what goes to whom (T3.1).

``Game`` sits between the table (``fish_server.table``, the rules and the timers) and the
connections. It takes events, each with the server-clock time it is handled at, and returns
what to do: send a message to a seat, release a person whose seat a bot took, or end the
game. It does no input or output, so it is tested on a fake clock; ``fish_server.hub`` runs
it on the real one and does the sending and the writing.

- After every change at the table, every connected person is sent their seat's update; a
  rejected input is answered with ``rejected`` and an update (R.8.3, R.8.7).
- Every connected person is pinged when they connect and every 5 seconds after; the round
  trip is recorded (R.8.7).
- A seat a bot holds acts once the stand-in delay has passed, if it may act and nothing has
  happened since. Until B1 and its delays (T3.5, R.8.8), the bot is a stand-in that chooses
  uniformly among the actions the website allows, and never presses Call.
- ``rows`` hands over the actions (once sent) and log rows not yet written.
"""

import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fish_agents.memory import NONE
from fish_rules.action_index import decode
from fish_rules.cards import SEATS, Seat
from fish_rules.codec import action_to_data
from fish_rules.state import Phase
from fish_server.protocol import Message, Ping, Rejected, update
from fish_server.table import SECOND_US, Controller, Entry, Table
from fish_server.table import Rejected as TableRejected

PING_US: Final = 5 * SECOND_US
"""R.8.7: every connected person's round trip is measured every 5 seconds."""

STAND_IN: Final = Controller("b0-v1", NONE)
"""The bot that takes over a person's seat until T3.5 brings B1."""

STAND_IN_DELAY_US: Final = 2 * SECOND_US
"""How long the stand-in waits before acting; T3.5 replaces it with R.8.8's drawn delays."""


# ---------------------------------------------------------------- events


@dataclass(frozen=True, slots=True)
class Pressed:
    seat: Seat
    set_id: int
    seen: int | None


@dataclass(frozen=True, slots=True)
class Acted:
    seat: Seat
    index: int


@dataclass(frozen=True, slots=True)
class Ponged:
    seat: Seat
    nonce: int


@dataclass(frozen=True, slots=True)
class Connected:
    seat: Seat


@dataclass(frozen=True, slots=True)
class Disconnected:
    seat: Seat


@dataclass(frozen=True, slots=True)
class Malformed:
    seat: Seat
    data: str


type Event = Pressed | Acted | Ponged | Connected | Disconnected | Malformed


# ---------------------------------------------------------------- what to do


@dataclass(frozen=True, slots=True)
class Send:
    seat: Seat
    message: Message


@dataclass(frozen=True, slots=True)
class Release:
    """A bot took this seat (R.8.4): its person is no longer at the table."""

    seat: Seat


@dataclass(frozen=True, slots=True)
class End:
    """The rules ended the game: ``completion`` is ``finished`` or ``unfinished``."""

    completion: str


type Out = Send | Release | End


class Game:
    """One table's game. ``seats[s]`` is the id of the person in seat s at the deal."""

    def __init__(
        self,
        game_id: uuid.UUID,
        seed: int,
        seats: Sequence[uuid.UUID],
        *,
        replacement: Controller = STAND_IN,
    ) -> None:
        self.game_id = game_id
        self.seats = tuple(seats)
        self.table = Table(seed, people=SEATS, replacement=replacement)
        self.ended = False
        self._people = self.table.people
        self._next_ping: dict[Seat, int] = {}
        self._pings: dict[int, tuple[Seat, int]] = {}  # nonce -> seat, when sent
        self._nonce = 0
        self._bot_due: dict[Seat, tuple[int, int]] = {}  # seat -> when, at which version
        self._choose = secrets.SystemRandom().choice
        self._saved_entries = 0
        self._saved_log = 0

    def seat_of(self, player: uuid.UUID) -> Seat | None:
        """The seat ``player`` holds now, or None (never seated here, or handed over)."""
        if player not in self.seats:
            return None
        seat = self.seats.index(player)
        return seat if seat in self.table.people else None

    # ------------------------------------------------------------ events and timers

    def handle(self, event: Event, now: int) -> list[Out]:
        """Apply ``event``, handled at ``now``."""
        table, outs = self.table, list[Out]()
        version, show = len(table.entries), set[Seat]()
        connected = {seat for seat in SEATS if table.connected(seat)}
        result = None
        match event:
            case Pressed(seat, set_id, seen):
                result = table.press(seat, set_id, seen, now)
            case Acted(seat, index):
                result = table.act(seat, decode(seat, index, table.state.phase), now)
            case Malformed(seat, data):
                result = table.reject(seat, data, "malformed", now)
            case Ponged(seat, nonce):
                sent = self._pings.get(nonce)
                if sent is not None and sent[0] == seat:
                    del self._pings[nonce]
                    table.round_trip(seat, now - sent[1], now)
            case Connected(seat):
                if table.connect(seat, now):
                    self._next_ping[seat] = now
                    show.add(seat)
            case _:  # Disconnected
                table.disconnect(event.seat, now)
                self._next_ping.pop(event.seat, None)
        if isinstance(result, TableRejected):
            data = {"type": "rejected", "reason": result.reason, "discarded": result.discarded}
            outs.append(Send(event.seat, Rejected.model_validate(data)))
            show.add(event.seat)  # and the state as it is now (R.8.7)
        changed = len(table.entries) != version
        return outs + self._after(now, changed=changed, show=show, connected=connected)

    def wake(self, now: int) -> list[Out]:
        """Let timers fire, bots act and pings go out, as due by ``now``."""
        table, outs = self.table, list[Out]()
        version = len(table.entries)
        connected = {seat for seat in SEATS if table.connected(seat)}
        table.advance(now)
        for seat, (due, at) in sorted(self._bot_due.items()):
            if due <= now and at == len(table.entries) and (actions := table.actions(seat)):
                del self._bot_due[seat]
                table.act(seat, self._choose(actions), now)
        for seat, due in sorted(self._next_ping.items()):
            if due <= now:
                self._nonce += 1
                self._pings[self._nonce] = (seat, now)
                self._next_ping[seat] = now + PING_US
                outs.append(Send(seat, Ping(type="ping", nonce=self._nonce)))
        changed = len(table.entries) != version
        return outs + self._after(now, changed=changed, connected=connected)

    def next_wake(self) -> int | None:
        """When ``wake`` next has something to do, or None."""
        if self.ended:
            return None
        due = [self.table.deadline(), *(d for d, _ in self._bot_due.values()),
               *self._next_ping.values()]  # fmt: skip
        return min((d for d in due if d is not None), default=None)

    # ------------------------------------------------------------ writing

    def rows(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """The ``actions`` and ``server_log`` rows not yet handed over, for this game. Actions
        are handed over once sent, so their sent times are known."""
        table = self.table
        sent: list[Entry] = []
        for entry in table.entries[self._saved_entries :]:
            if entry.sent_us is None:
                break
            sent.append(entry)
        actions = [
            {
                "game_id": self.game_id,
                "seq": self._saved_entries + n,
                "action": action_to_data(entry.action),
                "cause_seat": entry.cause.get("seat"),
                "cause_timer": entry.cause.get("timer"),
                "received_us": entry.received_us,
                "sent_us": entry.sent_us,
            }
            for n, entry in enumerate(sent)
        ]
        log = [
            {
                "game_id": self.game_id,
                "after_seq": row["after"],
                "at_us": row["at_us"],
                "seat": row["seat"],
                "type": row["type"],
                "data": {
                    k: v for k, v in row.items() if k not in ("type", "after", "at_us", "seat")
                },
            }
            for row in table.log[self._saved_log :]
        ]
        self._saved_entries += len(sent)
        self._saved_log = len(table.log)
        return actions, log

    # ------------------------------------------------------------ inside

    def _after(
        self, now: int, *, changed: bool, connected: set[Seat], show: set[Seat] | None = None
    ) -> list[Out]:
        """What follows any change: updates (to a person handed over just now, if they were
        connected, a last one), releases, the bots' next turns, the end."""
        table, outs = self.table, list[Out]()
        handed = self._people - table.people
        self._people = table.people
        everyone = changed or bool(handed)
        for seat in SEATS:
            if (table.connected(seat) and (everyone or seat in (show or ()))) or (
                seat in handed and seat in connected
            ):
                outs.append(Send(seat, update(table, seat, now)))
        for seat in sorted(handed):
            self._next_ping.pop(seat, None)
            outs.append(Release(seat))
        version = len(table.entries)
        for seat in SEATS:
            if seat in table.people or not table.actions(seat):
                self._bot_due.pop(seat, None)
            elif self._bot_due.get(seat, (0, -1))[1] != version:
                self._bot_due[seat] = (now + STAND_IN_DELAY_US, version)
        if table.state.phase is Phase.OVER and not self.ended:
            self.ended = True
            self._next_ping.clear()
            self._bot_due.clear()
            outs.append(End(str(table.state.outcome)))
        return outs
