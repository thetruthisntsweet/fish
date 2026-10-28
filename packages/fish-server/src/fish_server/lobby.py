"""Matchmaking: the solo queue and group rooms (T3.1).

Players wait in exactly one place at a time: the solo queue or one room. A table forms the
moment six are waiting together; T3.5 will fill seats with bots when people are short.

**Solo matchmaking** keeps two queues, one for the held-out cohort and one for everyone else,
so cohort players are matched only with each other (docs/corpus.md §2.1). A table formed from
the cohort queue is a *cohort table*. The six who have waited longest form it.

**Group rooms** let friends play together. One player creates a room and shares its code; up
to six join it, cohort or not, and the table forms when the sixth arrives. A group table is
never a cohort table: one with both cohort and other players is left out of the cohort test
set and of training (§6).

Seats are drawn at random for each table, so who sits with whom, and so who partners whom, is
chance and not join order. Everything here is in memory, in the server's one process; a
restart empties the queues and rooms, and players join again.

``Lobby`` decides; it never touches the network or the database. Its methods return what
changed, and the game loop (subtask 6) tells players and starts tables.
"""

import secrets
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from fish_rules.cards import NUM_SEATS
from fish_server.protocol import ROOM_CODE_ALPHABET, ROOM_CODE_LENGTH

type Matchmaking = Literal["solo", "group"]


@dataclass(frozen=True, slots=True)
class Player:
    """A signed-in player, and whether they are in the held-out cohort (§2.1)."""

    id: uuid.UUID
    cohort: bool


@dataclass(frozen=True, slots=True)
class Formed:
    """A new table: ``seats[s]`` is the player in seat s."""

    seats: tuple[Player, ...]
    matchmaking: Matchmaking
    cohort_table: bool


@dataclass(frozen=True, slots=True)
class Waiting:
    """Where a player waits: ``matchmaking`` and, for a room, its ``code``; ``people`` counts
    everyone waiting there, the player included."""

    matchmaking: Matchmaking
    code: str | None
    people: int


class NotNowError(Exception):
    """A real request that does not fit the player's situation: joining while already
    waiting or seated, or a room that does not exist."""


@dataclass
class _Room:
    code: str
    members: list[Player] = field(default_factory=list[Player])


def _shuffle(players: list[Player]) -> None:
    """Draw the seats with the operating system's randomness, never a seeded generator, so no
    one can predict or choose where they sit."""
    secrets.SystemRandom().shuffle(players)


class Lobby:
    """The queues and rooms. ``shuffle`` and ``new_code`` are replaced in tests."""

    def __init__(
        self,
        shuffle: Callable[[list[Player]], None] = _shuffle,
        new_code: Callable[[], str] | None = None,
    ) -> None:
        self._shuffle = shuffle
        self._new_code = new_code or _random_code
        self._queues: dict[bool, list[Player]] = {True: [], False: []}
        self._rooms: dict[str, _Room] = {}
        self._room_of: dict[uuid.UUID, str] = {}
        self.seated: set[uuid.UUID] = set()
        """Players at a table now. They may not wait anywhere until it ends (``left_table``)."""

    # ------------------------------------------------------------ where players are

    def waiting(self, player: Player) -> Waiting | None:
        """Where ``player`` waits, or None."""
        code = self._room_of.get(player.id)
        if code is not None:
            return Waiting("group", code, len(self._rooms[code].members))
        queue = self._queues[player.cohort]
        if any(p.id == player.id for p in queue):
            return Waiting("solo", None, len(queue))
        return None

    def others(self, player: Player) -> tuple[Player, ...]:
        """Everyone waiting where ``player`` waits, the player included: whom to tell when the
        count there changes."""
        code = self._room_of.get(player.id)
        if code is not None:
            return tuple(self._rooms[code].members)
        queue = self._queues[player.cohort]
        return tuple(queue) if any(p.id == player.id for p in queue) else ()

    # ------------------------------------------------------------ joining and leaving

    def join_queue(self, player: Player) -> Formed | None:
        """Put ``player`` in the solo queue for their cohort; the table, if six now wait."""
        self._free(player)
        queue = self._queues[player.cohort]
        queue.append(player)
        if len(queue) < NUM_SEATS:
            return None
        chosen, self._queues[player.cohort] = queue[:NUM_SEATS], queue[NUM_SEATS:]
        return self._form(chosen, "solo", cohort_table=player.cohort)

    def create_room(self, player: Player) -> str:
        """A new room with ``player`` in it; returns its code."""
        self._free(player)
        code = self._new_code()
        while code in self._rooms:
            code = self._new_code()
        self._rooms[code] = _Room(code, [player])
        self._room_of[player.id] = code
        return code

    def join_room(self, player: Player, code: str) -> Formed | None:
        """Put ``player`` in room ``code``; the table, if it is now full."""
        room = self._rooms.get(code)
        if room is None:
            raise NotNowError("there is no room with that code")
        self._free(player)
        room.members.append(player)
        self._room_of[player.id] = code
        if len(room.members) < NUM_SEATS:
            return None
        del self._rooms[code]
        for member in room.members:
            del self._room_of[member.id]
        return self._form(room.members, "group", cohort_table=False)

    def leave(self, player: Player) -> tuple[Player, ...]:
        """Stop ``player`` waiting, wherever they wait. Returns those still waiting there, who
        are told the new count. Leaving when not waiting changes nothing."""
        code = self._room_of.pop(player.id, None)
        if code is not None:
            room = self._rooms[code]
            room.members = [p for p in room.members if p.id != player.id]
            if not room.members:
                del self._rooms[code]
            return tuple(room.members)
        queue = self._queues[player.cohort]
        if not any(p.id == player.id for p in queue):
            return ()
        self._queues[player.cohort] = [p for p in queue if p.id != player.id]
        return tuple(self._queues[player.cohort])

    def left_table(self, players: Sequence[Player]) -> None:
        """The table these players sat at has ended (or they left it): they may wait again."""
        self.seated -= {p.id for p in players}

    # ------------------------------------------------------------ inside

    def _free(self, player: Player) -> None:
        if player.id in self.seated:
            raise NotNowError("you are at a table")
        if self.waiting(player) is not None:
            raise NotNowError("you are already waiting; leave first")

    def _form(self, players: list[Player], how: Matchmaking, *, cohort_table: bool) -> Formed:
        seats = list(players)
        self._shuffle(seats)
        self.seated |= {p.id for p in seats}
        return Formed(tuple(seats), how, cohort_table)


def _random_code() -> str:
    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
