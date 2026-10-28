"""The game server's live part: connections, the lobby and the games in progress (T3.1).

Everything runs on the server's one event loop, in one process: the lobby (who waits where),
every game's table, and every connection. Game state lives in memory and is written to the
database as it happens.

**Connections.** ``/ws`` accepts a connection only with a valid session cookie, then expects
``client_hello`` with this server's protocol version. A player has one connection: a new one
replaces the old, which is closed. What a connection is sent goes into its own queue and a
task sends it, so a slow client never holds up anyone else; a message counts as sent (an
action's ``sent_us``) once it is in every connected seat's queue.

**The lobby.** Only a player who has accepted the study information this site shows, and
has not withdrawn, may wait for a game (Consent Screen §2); anyone else is told why.

**Games.** Each game has one task. It takes the game's inputs in the order they arrive and
stamps each with the server clock as it takes it, so the table applies them in that order
(R.8.7, R.8.5), and it sleeps until the next timer, bot action or ping is due. After every
step it sends what ``fish_server.game.Game`` says to send, stamps the actions sent, and gives
the new rows to the game's writer, which writes them in order from a thread so the database
never blocks the event loop. When the rules end the game, its ending is written, after a
check that its stored log has no gap, and its players return to the lobby.

**After a game** the rules ended, each person still in it and connected is asked the
note-taking question (``note_question``); their ``note_answer`` is written for their seat. A
person who leaves, or starts another game, without answering is ``unanswered``
(docs/corpus.md §4.2). Abandoned games ask nothing: they never enter the corpus.

**When a game cannot go on** (T3.2; docs/corpus.md §3), it ends ``abandoned``, and its
players are told why:

- *The server shuts down* (a deploy, a restart): every game is stopped, its rows written,
  and its ending written as ``abandoned``.
- *A write keeps failing*: it is retried for about a minute (``RETRY_S``), then the game is
  stopped and nothing more of it is written, since a log with a gap cannot replay it.
- *The server crashed*, or the database was down when it stopped: the game has no ending.
  Every minute, and at start, the server marks ``abandoned`` each game without an ending that
  is not running here and has written nothing for five minutes (``games.abandon_quiet``). A
  live game writes every few seconds, so during a deploy the old server's games, still being
  played, are never caught.
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Engine, insert
from sqlalchemy.dialects.postgresql import insert as upsert

from fish_server import db
from fish_server.consent import standing
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
from fish_server.games import abandon_quiet, new_seed, start_game, write_ending
from fish_server.lobby import Formed, Lobby, NotNowError, Player
from fish_server.protocol import (
    NOTE_QUESTION_VERSION,
    Act,
    CreateRoom,
    JoinQueue,
    JoinRoom,
    Leave,
    Message,
    NoteAnswer,
    Pong,
    Press,
    ServerError,
    note_question,
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


SWEEP_S: Final = 60.0
"""How often the server looks for games a crash or a restart left without an ending."""

RETRY_S: Final = (0.5, 1, 2, 4, 8, 16, 30)
"""The waits between attempts at a write that fails: about a minute in all, enough for the
database to come back from a restart or a failover, before the game is stopped."""


class Running:
    """A game in progress: its ``Game``, its input queue, its task and its writer."""

    def __init__(
        self,
        hub: Hub,
        game: Game,
        players: tuple[Player, ...],
        start_ns: int,
        retry_s: tuple[float, ...] = RETRY_S,
    ) -> None:
        self.hub = hub
        self.game = game
        self.players = players
        self.start_ns = start_ns
        self.retry_s = retry_s
        self.inputs: asyncio.Queue[Event | None] = asyncio.Queue()
        self.writes: asyncio.Queue[Callable[[], None] | None] = asyncio.Queue()
        self.stopped: str | None = None
        """Why the game was stopped before the rules ended it, once it has been."""
        self.lost = False
        """A write failed for good: the database holds only part of the game."""
        for seat, player in enumerate(players):  # first, before anything they send
            if player.id in hub.connections:
                self.inputs.put_nowait(Connected(seat))

    def now(self) -> int:
        return (time.monotonic_ns() - self.start_ns) // 1000

    def stop(self, why: str) -> None:
        """Stop the game before the rules end it, telling its players ``why``."""
        if self.stopped is None:
            self.stopped = why
            self.inputs.put_nowait(None)

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
                    continue
                if event is None:
                    break
                self._do(self.game.handle(event, self.now()))
        finally:
            if not self.game.ended:
                self._abandon()
            self.writes.put_nowait(None)
            await writer

    def _do(self, outs: list[Send | Release | End]) -> None:
        hub = self.hub
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
        self._save()
        if ending is not None:
            self._end(ending)

    def _save(self) -> None:
        """Stamp what was just sent, and queue the rows not yet written."""
        game, hub = self.game, self.hub
        game.table.sent(self.now())  # every update is in its queue: the actions are sent
        actions, log = game.rows()
        if (actions or log) and not self.lost:
            self.writes.put_nowait(lambda: hub.write_rows(actions, log))

    def _end(self, completion: str) -> None:
        """Queue the ending, after every row; once the rules ended the game, ask each person
        still in it the note-taking question; and send the players back to the lobby."""
        game, hub = self.game, self.hub
        played = len(game.table.entries)
        if not self.lost:  # with rows lost the game stays without one, for the sweep
            self.writes.put_nowait(lambda: hub.write_ending(game, completion, played))
        if completion != "abandoned" and not self.lost:
            for player in self.players:
                seat = game.seat_of(player.id)
                if seat is not None and player.id in hub.connections:
                    hub.ask(player, game.game_id, seat)
        for player in self.players:
            hub.release(self, player)

    def _abandon(self) -> None:
        """The game stops before the rules end it (docs/corpus.md §3): write what it has,
        end it ``abandoned``, and tell everyone still at the table why."""
        why = self.stopped or "The game had to stop."
        for player in self.players:
            if self.hub.games.get(player.id) is self:
                connection = self.hub.connections.get(player.id)
                if connection is not None:
                    connection.send(error("not_now", why))
        self._save()
        self._end("abandoned")

    async def _write(self) -> None:
        """Write each job in order; retry a failing one, and if it never succeeds, stop the
        game and write nothing more, since a log with a gap could not replay it."""
        while (job := await self.writes.get()) is not None:
            if self.lost:
                continue
            for wait in (*self.retry_s, None):
                try:
                    await asyncio.to_thread(job)
                    break
                except Exception as problem:  # the database is down, or refused a row
                    print(f"game {self.game.game_id}: a write failed: {problem!r}", flush=True)
                    if wait is None:
                        self.lost = True
                        self.stop("The game had to stop: its moves could not be saved.")
                    else:
                        await asyncio.sleep(wait)


class Hub:
    """The lobby, the connections and the games in progress."""

    def __init__(
        self,
        engine: Callable[[], Engine],
        server_commit: str,
        consent_version: str = "v1.0",
        sweep_s: float = SWEEP_S,
    ) -> None:
        self.engine = engine
        self.server_commit = server_commit
        self.consent_version = consent_version
        self.lobby = Lobby()
        self.connections: dict[uuid.UUID, Connection] = {}
        self.games: dict[uuid.UUID, Running] = {}  # player -> the game they are in
        self.running: set[Running] = set()  # every game in progress here, bots' too
        self.notes: dict[uuid.UUID, tuple[uuid.UUID, int]] = {}  # player -> game, seat asked
        self.tasks: set[asyncio.Task[None]] = set()  # the games' tasks
        self.sweep_s = sweep_s
        self.sweeper: asyncio.Task[None] | None = None
        self.closing = asyncio.Event()

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
        self.notes.pop(player.id, None)  # left without answering: unanswered
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
        elif isinstance(message, NoteAnswer):
            await self._answer(connection, message.answer)
        else:  # a second hello
            connection.send(error("not_now", "Hello again: nothing to do."))

    # ------------------------------------------------------------ the lobby

    async def _lobby(self, connection: Connection, message: Message) -> None:
        player = connection.player
        if not isinstance(message, Leave):
            refused = await asyncio.to_thread(self.refusal, player)
            if refused is not None:
                connection.send(error("not_now", refused))
                return
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

    # ------------------------------------------------------------ the note-taking question

    def ask(self, player: Player, game: uuid.UUID, seat: int) -> None:
        """Ask ``player``, who held ``seat`` to the end of ``game``, the note-taking question
        (docs/corpus.md §4.2)."""
        self.notes[player.id] = (game, seat)
        if (connection := self.connections.get(player.id)) is not None:
            connection.send(note_question())

    async def _answer(self, connection: Connection, answer: str) -> None:
        asked = self.notes.pop(connection.player.id, None)
        if asked is None:
            connection.send(error("not_now", "There is no question to answer."))
            return
        try:
            await asyncio.to_thread(self.write_note, *asked, answer)
        except Exception as problem:  # the answer is lost: it counts as unanswered
            print(f"game {asked[0]}: a note answer could not be written: {problem!r}", flush=True)

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
        except Exception as problem:  # tell the players; they can try again
            print(f"a game could not start: {problem!r}", flush=True)
            self.lobby.left_table(formed.seats)
            for player in formed.seats:
                if (connection := self.connections.get(player.id)) is not None:
                    connection.send(error("not_now", "The game could not start. Try again."))
                    connection.send(lobby_message(self.lobby, player))
            return
        for player in formed.seats:  # playing on without answering: unanswered
            self.notes.pop(player.id, None)
        game = Game(game_id, seed, [p.id for p in formed.seats])
        running = Running(self, game, formed.seats, start_ns)
        for player in formed.seats:
            self.games[player.id] = running
        self.running.add(running)
        self._spawn(running.run(), lambda: self.running.discard(running))

    def _spawn(self, work: Coroutine[None, None, None], done: Callable[[], None]) -> None:
        task = asyncio.create_task(work)
        self.tasks.add(task)

        def finished(task: asyncio.Task[None]) -> None:
            self.tasks.discard(task)
            done()

        task.add_done_callback(finished)

    def release(self, running: Running, player: Player) -> None:
        """``player`` is no longer at ``running``'s table: free them for the lobby."""
        if self.games.get(player.id) is running:
            del self.games[player.id]
            self.lobby.left_table([player])
            if (connection := self.connections.get(player.id)) is not None:
                connection.send(lobby_message(self.lobby, player))

    # ------------------------------------------------------------ writing (in a thread)

    def refusal(self, player: Player) -> str | None:
        """Why ``player`` may not wait for a game now: they have not accepted the current
        study information, or they have withdrawn (``fish_server.consent``)."""
        with self.engine().connect() as conn:
            return standing(conn, player.id, self.consent_version).refusal()

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

    def write_ending(self, game: Game, completion: str, played: int) -> None:
        with self.engine().begin() as conn:
            written = write_ending(conn, game.game_id, completion, played)
        if written != completion:
            print(f"game {game.game_id}: its log has a gap, so it is abandoned", flush=True)

    def write_note(self, game: uuid.UUID, seat: int, answer: str) -> None:
        """Write one seat's note answer, with the question's version; once only."""
        row = {"game_id": game, "seat": seat, "answer": answer,
               "question_version": NOTE_QUESTION_VERSION}  # fmt: skip
        with self.engine().begin() as conn:
            conn.execute(upsert(db.note_answers).values(**row).on_conflict_do_nothing())

    def sweep(self) -> list[uuid.UUID]:
        """Mark abandoned the games a crash or a restart stopped (``games.abandon_quiet``)."""
        here = [running.game.game_id for running in self.running]
        with self.engine().begin() as conn:
            return abandon_quiet(conn, running=here)

    async def _sweeping(self) -> None:
        while not self.closing.is_set():
            try:
                for game in await asyncio.to_thread(self.sweep):
                    print(f"game {game}: stopped without an ending; now abandoned", flush=True)
            except Exception as problem:  # the database may be down; try next time
                print(f"the sweep for stopped games failed: {problem!r}", flush=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.closing.wait(), self.sweep_s)

    def start(self) -> None:
        """Start the sweep for games stopped without an ending, now and every ``sweep_s``."""
        self.sweeper = asyncio.create_task(self._sweeping())

    async def close(self, grace_s: float = 10) -> None:
        """The server is shutting down: stop every game, which ends it ``abandoned`` and
        writes it out, wait up to ``grace_s`` for that, then cancel whatever is left."""
        self.closing.set()  # the sweep finishes what it is doing, then stops
        for running in list(self.running):
            running.stop("The server is restarting, so this game has ended.")
        waiting = [*self.tasks, *([self.sweeper] if self.sweeper else [])]
        if waiting:
            await asyncio.wait(waiting, timeout=grace_s)
        tasks = [task for task in waiting if not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
