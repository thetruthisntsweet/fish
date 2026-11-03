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
- A seat a bot holds is played by B1 (``b1-v1``) remembering the latest 8 events (T3.5;
  Research Plan §5). It is shown every view its seat is shown from the moment it takes the
  seat, and acts once its wait has passed (R.8.8, ``fish_server.bots``), if it may act and
  nothing has happened since; a wait the game overtook is recorded as dropped, and a new one
  is drawn. It chooses among the actions the website allows, so on a turn only an ask, with
  its random choices from the game's ``bot_policy`` stream (``fish_agents.PolicyStreams``):
  a game's bots play the same from the same seed.
- After every event, and when it takes a seat, each bot decides whether to press Call
  (R.8.8): B1 presses for a call it can prove (``fish_agents.b1.would_call``). Once its wait
  has passed it presses, if no window, assignment, choice or run-out is in progress then;
  otherwise the decision is dropped. A newer event replaces a decision still waiting, so a
  bot never declares in a window someone else opened. A bot whose turn offers no ask holds
  only whole sets (R.3.2), so it can always prove a call and presses one (R.9).
- ``rows`` hands over the actions (once sent) and log rows not yet written.
"""

import dataclasses
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fish_agents.b1 import B1_VERSION, b1, would_call
from fish_agents.base import PolicyStreams
from fish_agents.memory import MemorySetting
from fish_rules.action_index import decode, encode
from fish_rules.cards import SEATS, Seat
from fish_rules.codec import action_to_data
from fish_rules.events import Action
from fish_rules.state import Phase
from fish_server.bots import DelayStreams
from fish_server.protocol import Message, Ping, Rejected, update
from fish_server.table import SECOND_US, Controller, Entry, Table
from fish_server.table import Rejected as TableRejected

PING_US: Final = 5 * SECOND_US
"""R.8.7: every connected person's round trip is measured every 5 seconds."""

BOT: Final = Controller(B1_VERSION, MemorySetting.last_k(8))
"""The bot that takes over a person's seat (R.8.4): B1 remembering the latest 8 events (T3.5;
D95)."""


@dataclass(frozen=True, slots=True)
class Pressing:
    """A bot's decision to press Call on ``set_id``, waiting for its delay: due ``due``,
    decided after ``events`` events (the press says it saw the last of them)."""

    due: int
    events: int
    delay_us: int
    set_id: int


@dataclass(frozen=True, slots=True)
class Waiting:
    """A bot's decision waiting for its delay: due ``due``, drawn when the table had
    ``version`` entries, after a wait of ``delay_us``."""

    due: int
    version: int
    delay_us: int


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
    ) -> None:
        self.game_id = game_id
        self.seats = tuple(seats)
        self.table = Table(seed, people=SEATS, replacement=BOT)
        self.ended = False
        self._people = self.table.people
        self._next_ping: dict[Seat, int] = {}
        self._pings: dict[int, tuple[Seat, int]] = {}  # nonce -> seat, when sent
        self._nonce = 0
        self._delays = DelayStreams(seed)
        self._bot_due: dict[Seat, Waiting] = {}
        self._press_due: dict[Seat, Pressing] = {}
        self._decided_at = 0  # the events the bots last decided their presses after
        self._bot = b1(BOT.memory)
        self._policy = PolicyStreams(seed)
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
        for seat, waiting in sorted(self._bot_due.items()):
            if waiting.due > now or waiting.version != len(table.entries):
                continue
            del self._bot_due[seat]  # the state it was drawn for: it may still act
            table.bot_waited(seat, waiting.delay_us, dropped=False, now=now)
            table.act(seat, self._decide(seat), now)
        for seat, pressing in sorted(self._press_due.items()):
            if pressing.due > now or pressing.events != table.state.events:
                continue  # not yet, or an event since (just now, by a bot): decided afresh
            del self._press_due[seat]
            live = table.state.phase is Phase.TURN and pressing.set_id in table.pressable(seat)
            table.bot_waited(seat, pressing.delay_us, dropped=not live, now=now)
            if live:
                seen = pressing.events - 1 if pressing.events else None
                table.press(seat, pressing.set_id, seen, now)
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
        due = [self.table.deadline(), *(w.due for w in self._bot_due.values()),
               *(p.due for p in self._press_due.values()), *self._next_ping.values()]  # fmt: skip
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
        for seat in SEATS:
            if seat not in table.people and (everyone or seat in handed):
                self._bot.observe(table.view(seat))  # every view its seat is shown
        version = len(table.entries)
        over = table.state.phase is Phase.OVER
        if not over:
            self._decide_presses(now, handed)
        for seat in SEATS:
            waiting = self._bot_due.get(seat)
            if waiting is not None and waiting.version == version:
                continue  # still waiting for this state
            if waiting is not None:
                del self._bot_due[seat]
                if not over:  # the game moved on before the wait was over
                    table.bot_waited(seat, waiting.delay_us, dropped=True, now=now)
            if seat not in table.people and not over and table.actions(seat):
                delay = self._delays.delay(seat, table.state.events)
                self._bot_due[seat] = Waiting(now + delay, version, delay)
        if over and not self.ended:
            self.ended = True
            self._next_ping.clear()
            self._bot_due.clear()
            self._press_due.clear()
            outs.append(End(str(table.state.outcome)))
        return outs

    def _decide(self, seat: Seat) -> Action:
        """B1's action for ``seat``, among those the website allows it now."""
        table = self.table
        allowed = table.actions(seat)
        view = table.view(seat)
        offered = dataclasses.replace(view, legal=tuple(sorted(encode(a) for a in allowed)))
        rng = self._policy.for_decision(seat, table.state.events)
        return decode(seat, self._bot.act(offered, rng), table.state.phase)

    def _decide_presses(self, now: int, handed: frozenset[Seat]) -> None:
        """After every event, each bot decides afresh whether to press Call (R.8.8), and a bot
        that has just taken a seat decides at once. A decision a newer event overtook is
        recorded as dropped."""
        table = self.table
        events = table.state.events
        anew = events != self._decided_at
        self._decided_at = events
        for seat in SEATS:
            if seat in table.people or not (anew or seat in handed):
                continue
            pressing = self._press_due.pop(seat, None)
            if pressing is not None:
                table.bot_waited(seat, pressing.delay_us, dropped=True, now=now)
            rng = self._policy.for_decision(seat, events)
            set_id = would_call(table.view(seat), self._bot.memory(seat).deduction, rng)
            if set_id is not None:
                delay = self._delays.delay(seat, events)
                self._press_due[seat] = Pressing(now + delay, events, delay, set_id)
