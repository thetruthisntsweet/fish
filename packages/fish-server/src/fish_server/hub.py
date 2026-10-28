"""The game server's live part: connections, the lobby and the games in progress (T3.1).

Everything runs on the server's one event loop, in one process: the lobby (who waits where),
every game's table, and every connection. Game state lives in memory and is written to the
database as it happens; a restart abandons games in progress (their logs stay, without an
ending; T3.2 marks them abandoned).

**Connections.** ``/ws`` accepts a connection only with a valid session cookie, then expects
``client_hello`` with this server's protocol version. A player has one connection: a new one
replaces the old, which is closed. What a connection is sent goes into its own queue and a
task sends it, so a slow client never holds up anyone else; a message counts as sent (an
action's ``sent_us``) once it is in every connected seat's queue.

**Games.** Each game has one task. It takes the game's inputs in the order they arrive and
stamps each with the server clock as it takes it, so the table applies them in that order
(R.8.7, R.8.5), and it sleeps until the next timer, bot action or ping is due. After every
step it sends what ``fish_server.game.Game`` says to send, stamps the actions sent, and gives
the new rows to the game's writer, which writes them in order from a thread so the database
never blocks the event loop. When the rules end the game, its ending is written and its
players return to the lobby.
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, insert

from fish_server import db
from fish_server.game import (
    Acted,
    Connected,
    Disconnected,
    End,
    Event,
    Game,
    Malformed,
    Ponged,
    Pressed,
    Release,
    Send,
)
from fish_server.games import new_seed, start_game
from fish_server.lobby import Formed, Lobby, NotNowError, Player
from fish_server.protocol import (
    Act,
    CreateRoom,
    JoinQueue,
    JoinRoom,
    Leave,
    Message,
    Pong,
    Press,
    ServerError,
    parse_client_message,
)
from fish_server.protocol import Lobby as LobbyMessage

type Sender = Callable[[str], Awaitable[None]]


@dataclass(eq=False)
class Connection:
    """One player's open WebSocket. ``send`` queues; ``run`` drains the queue."""

    player: Player
    transmit: Sender
    shut: Callable[[], Awaitable[None]]
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue[str | None])

    def send(self, message: Message) -> None:
        self.queue.put_nowait(message.model_dump_json())

    def close(self) -> None:
        self.queue.put_nowait(None)

    async def run(self) -> None:
        """Send everything queued, in order, until closed; then close the socket."""
        while (text := await self.queue.get()) is not None:
            await self.transmit(text)
        await self.shut()


def error(code: str, message: str) -> ServerError:
    return ServerError.model_validate({"type": "error", "code": code, "message": message})


def lobby_message(lobby: Lobby, player: Player) -> LobbyMessage:
    where = lobby.waiting(player)
    if where is None:
        return LobbyMessage(type="lobby", waiting=None, code=None, people=0)
    data = {"waiting": where.matchmaking, "code": where.code, "people": where.people}
    return LobbyMessage(type="lobby", **data)  # pyright: ignore[reportArgumentType]


class Running:
    """A game in progress: its ``Game``, its input queue, its task and its writer."""

    def __init__(self, hub: Hub, game: Game, players: tuple[Player, ...], start_ns: int) -> None:
        self.hub = hub
        self.game = game
        self.players = players
        self.start_ns = start_ns
        self.inputs: asyncio.Queue[Event] = asyncio.Queue()
        self.writes: asyncio.Queue[Callable[[], None] | None] = asyncio.Queue()
        for seat, player in enumerate(players):  # first, before anything they send
            if player.id in hub.connections:
                self.inputs.put_nowait(Connected(seat))

    def now(self) -> int:
        return (time.monotonic_ns() - self.start_ns) // 1000

    async def run(self) -> None:
        writer = asyncio.create_task(self._write())
        try:
            while not self.game.ended:
                due = self.game.next_wake()
                timeout = None if due is None else max(0, due - self.now()) / 1_000_000
                try:
                    event = await asyncio.wait_for(self.inputs.get(), timeout)
                except TimeoutError:
                    self._do(self.game.wake(self.now()))
                else:
                    self._do(self.game.handle(event, self.now()))
        finally:
            self.writes.put_nowait(None)
            await writer

    def _do(self, outs: list[Send | Release | End]) -> None:
        game, hub = self.game, self.hub
        ending = None
        for out in outs:
            match out:
                case Send(seat, message):
                    connection = hub.connections.get(self.players[seat].id)
                    if connection is not None:
                        connection.send(message)
                case Release(seat):
                    hub.release(self, self.players[seat])
                case _:  # End
                    ending = out.completion
        game.table.sent(self.now())  # every update is in its queue: the actions are sent
        actions, log = game.rows()
        if actions or log:
            self.writes.put_nowait(lambda: hub.write_rows(actions, log))
        if ending is not None:
            self.writes.put_nowait(lambda: hub.write_ending(game, ending))
            for player in self.players:
                hub.release(self, player)

    async def _write(self) -> None:
        while (job := await self.writes.get()) is not None:
            try:
                await asyncio.to_thread(job)
            except Exception as problem:
                print(f"game {self.game.game_id}: a write failed: {problem!r}", flush=True)


class Hub:
    """The lobby, the connections and the games in progress."""

    def __init__(self, engine: Callable[[], Engine], server_commit: str) -> None:
        self.engine = engine
        self.server_commit = server_commit
        self.lobby = Lobby()
        self.connections: dict[uuid.UUID, Connection] = {}
        self.games: dict[uuid.UUID, Running] = {}  # player -> the game they are in
        self.tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ connections

    def connect(self, connection: Connection) -> None:
        """A signed-in player said hello: replace any older connection, then show them their
        game if they are in one, else the lobby."""
        player = connection.player
        old = self.connections.get(player.id)
        if old is not None:
            old.send(error("not_now", "You opened Fish somewhere else."))
            old.close()
        self.connections[player.id] = connection
        running = self.games.get(player.id)
        if running is not None:
            seat = running.game.seat_of(player.id)
            if seat is not None:
                running.inputs.put_nowait(Connected(seat))
                return
        connection.send(lobby_message(self.lobby, player))

    def disconnect(self, connection: Connection) -> None:
        """A connection closed. If it was the player's: leave any queue or room, and tell
        their game."""
        player = connection.player
        if self.connections.get(player.id) is not connection:
            return
        del self.connections[player.id]
        self._tell(self.lobby.leave(player))
        running = self.games.get(player.id)
        if running is not None and (seat := running.game.seat_of(player.id)) is not None:
            running.inputs.put_nowait(Disconnected(seat))

    async def receive(self, connection: Connection, raw: str) -> None:
        """One message from a connection."""
        player = connection.player
        running = self.games.get(player.id)
        seat = None if running is None else running.game.seat_of(player.id)
        try:
            message = parse_client_message(raw)
        except ValueError:
            if running is not None and seat is not None:
                running.inputs.put_nowait(Malformed(seat, raw[:1000]))
            connection.send(error("bad_message", "That is not a message this server knows."))
            return
        if isinstance(message, Press | Act | Pong):
            if running is None or seat is None:
                if not isinstance(message, Pong):
                    connection.send(error("not_now", "You are not at a table."))
                return
            match message:
                case Press(set_id=set_id, seen=seen):
                    running.inputs.put_nowait(Pressed(seat, set_id, seen))
                case Act(index=index):
                    running.inputs.put_nowait(Acted(seat, index))
                case _:  # Pong
                    running.inputs.put_nowait(Ponged(seat, message.nonce))
        elif isinstance(message, JoinQueue | CreateRoom | JoinRoom | Leave):
            await self._lobby(connection, message)
        else:  # a second hello
            connection.send(error("not_now", "Hello again: nothing to do."))

    # ------------------------------------------------------------ the lobby

    async def _lobby(self, connection: Connection, message: Message) -> None:
        player = connection.player
        try:
            match message:
                case JoinQueue():
                    formed = self.lobby.join_queue(player)
                case CreateRoom():
                    self.lobby.create_room(player)
                    formed = None
                case JoinRoom(code=code):
                    formed = self.lobby.join_room(player, code)
                case _:
                    self._tell(self.lobby.leave(player))
                    connection.send(lobby_message(self.lobby, player))
                    return
        except NotNowError as refused:
            connection.send(error("not_now", f"{str(refused).capitalize()}."))
            return
        if formed is None:
            self._tell(self.lobby.others(player))
        else:
            await self._start(formed)

    def _tell(self, players: tuple[Player, ...]) -> None:
        for player in players:
            connection = self.connections.get(player.id)
            if connection is not None:
                connection.send(lobby_message(self.lobby, player))

    # ------------------------------------------------------------ games

    async def _start(self, formed: Formed) -> None:
        seed, started = new_seed(), datetime.now(UTC)
        start_ns = time.monotonic_ns()
        try:
            game_id = await asyncio.to_thread(self._write_start, formed, seed, started)
        except Exception as problem:
            print(f"a game could not start: {problem!r}", flush=True)
            self.lobby.left_table(formed.seats)
            for player in formed.seats:
                if (connection := self.connections.get(player.id)) is not None:
                    connection.send(error("not_now", "The game could not start. Try again."))
                    connection.send(lobby_message(self.lobby, player))
            return
        game = Game(game_id, seed, [p.id for p in formed.seats])
        running = Running(self, game, formed.seats, start_ns)
        for player in formed.seats:
            self.games[player.id] = running
        task = asyncio.create_task(running.run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def release(self, running: Running, player: Player) -> None:
        """``player`` is no longer at ``running``'s table: free them for the lobby."""
        if self.games.get(player.id) is running:
            del self.games[player.id]
            self.lobby.left_table([player])
            if (connection := self.connections.get(player.id)) is not None:
                connection.send(lobby_message(self.lobby, player))

    # ------------------------------------------------------------ writing (in a thread)

    def _write_start(self, formed: Formed, seed: int, started: datetime) -> uuid.UUID:
        with self.engine().begin() as conn:
            return start_game(
                conn, formed, seed=seed, server_commit=self.server_commit, started_at=started
            )

    def write_rows(self, actions: list[dict[str, object]], log: list[dict[str, object]]) -> None:
        with self.engine().begin() as conn:
            if actions:
                conn.execute(insert(db.actions), actions)
            if log:
                conn.execute(insert(db.server_log), log)

    def write_ending(self, game: Game, completion: str) -> None:
        with self.engine().begin() as conn:
            ending = {"game_id": game.game_id, "completion": completion}
            conn.execute(insert(db.game_endings).values(**ending))

    async def close(self) -> None:
        """Stop every game task (the server is shutting down)."""
        for task in list(self.tasks):
            task.cancel()
        for task in list(self.tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
