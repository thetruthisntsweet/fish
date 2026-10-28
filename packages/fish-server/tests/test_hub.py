"""The hub's plumbing (T3.1), without sockets or a database: messages reach the right game, a
game's outputs reach the right connections in order, rows are written in order and an ending
after them, players return to the lobby when a game ends or a bot takes their seat, and a
failed write or a game that cannot start is survived."""

import asyncio
import json
import uuid
from typing import Any

import pytest

from fish_server.game import Acted, Connected, End, Malformed, Ponged, Release, Send
from fish_server.hub import Connection, Hub, Running
from fish_server.lobby import Formed, Player
from fish_server.protocol import Ping


class Recorder:
    """A connection's far end: what was sent, and whether it was closed."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def transmit(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def shut(self) -> None:
        self.closed = True


class Writes(Hub):
    """A hub whose database writes are recorded instead of made."""

    def __init__(self, *, fail: bool = False, failures: int = 0) -> None:
        super().__init__(lambda: None, "test")  # pyright: ignore[reportArgumentType]
        self.done: list[tuple[str, object]] = []
        self.fail = fail
        self.failures = failures  # how many writes of rows fail before they work

    def _write_start(self, formed: Formed, seed: int, started: object) -> uuid.UUID:  # pyright: ignore[reportIncompatibleMethodOverride]
        if self.fail:
            raise RuntimeError("database down")
        return uuid.uuid4()

    def write_rows(self, actions: list[dict[str, object]], log: list[dict[str, object]]) -> None:
        if self.fail or self.failures:
            self.failures = max(0, self.failures - 1)
            raise RuntimeError("database down")
        self.done.append(("rows", len(actions) + len(log)))

    def refusal(self, player: Player) -> str | None:
        return None

    def write_ending(self, game: object, completion: str, played: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self.done.append(("ending", completion))


class Table:
    entries: tuple[()] = ()

    def sent(self, now: int) -> int:
        return 0


class Forever:
    """A game the rules never end: it waits for input that never changes anything."""

    def __init__(self) -> None:
        self.game_id = uuid.uuid4()
        self.table = Table()
        self.ended = False
        self.given = False

    def seat_of(self, player: uuid.UUID) -> int | None:
        return 0

    def next_wake(self) -> int | None:
        return None

    def handle(self, event: object, now: int) -> list[object]:
        return []

    def rows(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        first, self.given = not self.given, True
        return ([{"seq": 0}], []) if first else ([], [])


class OneStep:
    """A game that ends at its first input: it sends a ping to seat 0, a bot takes seat 1,
    and the rules end it."""

    def __init__(self, seat: int | None = 0) -> None:
        self.seat = seat
        self.gone: set[uuid.UUID] = set()  # players a bot replaced
        self.game_id = uuid.uuid4()
        self.table = Table()
        self.ended = False
        self.events: list[object] = []

    def seat_of(self, player: uuid.UUID) -> int | None:
        return None if player in self.gone else self.seat

    def next_wake(self) -> int | None:
        return None

    def handle(self, event: object, now: int) -> list[object]:
        self.events.append(event)
        if isinstance(event, Connected):
            return []
        self.ended = True
        ping = Ping(type="ping", nonce=1)
        return [Send(0, ping), Send(2, ping), Release(1), End("finished")]

    def wake(self, now: int) -> list[object]:  # pragma: no cover - never due
        return []

    def rows(self) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return ([{"seq": 0}], []) if self.ended else ([], [])


def players(n: int) -> tuple[Player, ...]:
    return tuple(Player(uuid.uuid4(), False) for _ in range(n))


def attach(hub: Hub, player: Player) -> tuple[Connection, Recorder]:
    far = Recorder()
    connection = Connection(player, far.transmit, far.shut)
    hub.connect(connection)
    return connection, far


async def drain(*connections: Connection) -> None:
    for connection in connections:
        connection.close()
        await connection.run()


def test_a_game_that_ends_is_written_and_its_players_return_to_the_lobby() -> None:
    async def scenario() -> None:
        hub, six = Writes(), players(6)
        conns = [attach(hub, p) for p in six[:2]]  # four of the six are not connected
        game = OneStep()
        game.gone.add(six[1].id)  # the bot that takes seat 1 (Release below) replaced them
        running = Running(hub, game, six, 0)  # pyright: ignore[reportArgumentType]
        for p in six:
            hub.games[p.id] = running
        hub.lobby.seated |= {p.id for p in six}
        running.inputs.put_nowait(Acted(0, 0))
        await running.run()
        assert [type(e) for e in game.events] == [Connected, Connected, Acted]
        assert hub.done == [("rows", 1), ("ending", "finished")]  # rows first, then the end
        assert hub.games == {}
        assert hub.lobby.seated == set()
        await drain(*(c for c, _ in conns))
        first, second = (far.sent for _, far in conns)
        assert [m["type"] for m in first] == ["lobby", "ping", "note_question", "lobby"]
        assert [m["type"] for m in second] == ["lobby", "lobby"]  # released: not asked
        assert hub.notes == {six[0].id: (game.game_id, 0)}

    asyncio.run(scenario())


def test_a_write_that_fails_is_tried_again(capsys: pytest.CaptureFixture[str]) -> None:
    async def scenario() -> None:
        hub = Writes(failures=2)
        running = Running(hub, OneStep(), players(6), 0, retry_s=(0, 0, 0))  # pyright: ignore[reportArgumentType]
        running.inputs.put_nowait(Acted(0, 0))
        await running.run()
        assert hub.done == [("rows", 1), ("ending", "finished")]
        assert not running.lost

    asyncio.run(scenario())
    assert capsys.readouterr().out.count("a write failed") == 2


def test_a_write_that_keeps_failing_stops_the_game_and_writes_nothing_more(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def scenario() -> None:
        hub, six = Writes(fail=True), players(6)
        conns = [attach(hub, p) for p in six[:1]]
        running = Running(hub, Forever(), six, 0, retry_s=(0,))  # pyright: ignore[reportArgumentType]
        for p in six:
            hub.games[p.id] = running
        running.inputs.put_nowait(Acted(0, 0))
        await running.run()
        assert running.lost
        assert running.stopped == "The game had to stop: its moves could not be saved."
        assert hub.done == []  # no ending: the sweep marks it abandoned later
        assert hub.games == {}
        await drain(*(c for c, _ in conns))
        sent = conns[0][1].sent
        assert {"type": "error", "code": "not_now", "message": running.stopped} in sent

    asyncio.run(scenario())
    assert capsys.readouterr().out.count("a write failed") == 2


def test_a_game_that_cannot_start_sends_its_players_back(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def scenario() -> None:
        hub, six = Writes(fail=True), players(6)
        conns = [attach(hub, p) for p in six]
        for connection, _ in conns[:5]:
            await hub.receive(connection, '{"type": "join_queue"}')
        hub.disconnect(conns[0][0])  # one leaves before the table forms
        await hub.receive(conns[0][0], '{"type": "join_queue"}')
        await hub.receive(conns[5][0], '{"type": "join_queue"}')
        assert hub.lobby.seated == set()
        await drain(*(c for c, _ in conns[1:]))
        assert conns[5][1].sent[-2]["message"] == "The game could not start. Try again."
        assert conns[5][1].sent[-1] == {"type": "lobby", "waiting": None, "code": None, "people": 0}

    asyncio.run(scenario())
    assert "could not start" in capsys.readouterr().out


def test_messages_at_a_table_go_to_its_game() -> None:
    async def scenario() -> None:
        hub, six = Writes(), players(6)
        game = OneStep()
        running = Running(hub, game, six, 0)  # pyright: ignore[reportArgumentType]
        hub.games[six[0].id] = running
        connection, _ = attach(hub, six[0])  # reconnecting into the game
        await hub.receive(connection, '{"type": "act", "index": 3}')
        await hub.receive(connection, '{"type": "pong", "nonce": 9}')
        await hub.receive(connection, "{oops")
        events = [running.inputs.get_nowait() for _ in range(4)]
        assert events == [Connected(0), Acted(0, 3), Ponged(0, 9), Malformed(0, "{oops")]
        hub.disconnect(connection)
        hub.disconnect(connection)  # already gone: nothing more
        assert running.inputs.qsize() == 1

    asyncio.run(scenario())


def test_a_player_whose_seat_a_bot_took_reconnects_to_the_lobby() -> None:
    async def scenario() -> None:
        hub, six = Writes(), players(6)
        running = Running(hub, OneStep(seat=None), six, 0)  # pyright: ignore[reportArgumentType]
        hub.games[six[0].id] = running
        connection, far = attach(hub, six[0])
        await hub.receive(connection, '{"type": "act", "index": 3}')
        await drain(connection)
        assert [m["type"] for m in far.sent] == ["lobby", "error"]
        assert running.inputs.empty()

    asyncio.run(scenario())


def test_a_released_player_is_shown_the_lobby() -> None:
    async def scenario() -> None:
        hub, six = Writes(), players(6)
        running = Running(hub, OneStep(), six, 0)  # pyright: ignore[reportArgumentType]
        hub.games[six[2].id] = running
        hub.release(running, six[2])
        hub.release(running, six[2])  # once only
        connection, far = attach(hub, six[2])
        await drain(connection)
        assert [m["type"] for m in far.sent] == ["lobby"]

    asyncio.run(scenario())


def test_shutting_down_abandons_every_game_and_says_why() -> None:
    async def scenario() -> None:
        hub, six = Writes(), players(6)
        connection, far = attach(hub, six[0])
        running = Running(hub, Forever(), six, 0)  # pyright: ignore[reportArgumentType]
        for p in six:
            hub.games[p.id] = running
        hub.running.add(running)
        hub._spawn(running.run(), lambda: hub.running.discard(running))  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)
        await hub.close()
        assert hub.done == [("rows", 1), ("ending", "abandoned")]
        assert hub.running == set()
        await drain(connection)
        assert "The server is restarting, so this game has ended." in [
            m.get("message") for m in far.sent
        ]

    asyncio.run(scenario())


def test_a_game_that_will_not_stop_is_cancelled() -> None:
    async def scenario() -> None:
        hub = Writes()

        async def stuck() -> None:
            await asyncio.Event().wait()

        hub._spawn(stuck(), lambda: None)  # pyright: ignore[reportPrivateUsage]
        await hub.close(grace_s=0.01)
        assert hub.tasks == set()

    asyncio.run(scenario())


def test_the_sweep_runs_at_start_and_again_and_survives_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    found = [uuid.uuid4()]

    class Sweeping(Writes):
        calls = 0

        def sweep(self) -> list[uuid.UUID]:
            Sweeping.calls += 1
            if Sweeping.calls == 1:
                raise RuntimeError("database down")
            return found

    async def scenario() -> None:
        hub = Sweeping()
        hub.sweep_s = 0.01
        hub.start()
        while Sweeping.calls < 3:
            await asyncio.sleep(0.01)
        await hub.close()

    asyncio.run(scenario())
    out = capsys.readouterr().out
    assert "the sweep for stopped games failed" in out
    assert f"game {found[0]}: stopped without an ending; now abandoned" in out


def test_stopping_twice_and_closing_an_idle_hub_change_nothing() -> None:
    async def scenario() -> None:
        hub, six = Writes(fail=True), players(6)
        running = Running(hub, Forever(), six, 0, retry_s=())  # pyright: ignore[reportArgumentType]
        hub.games[six[0].id] = running  # only one of the six is still at the table
        running.stop("first")
        running.stop("second")
        await running.run()
        assert running.stopped == "first"
        running.writes.put_nowait(lambda: None)  # once lost, nothing more is written
        running.writes.put_nowait(None)
        await running._write()  # pyright: ignore[reportPrivateUsage]
        await Writes().close()

    asyncio.run(scenario())


def test_a_note_answer_is_written_for_the_seat_asked_once() -> None:
    async def scenario() -> None:
        hub, game = Writes(), uuid.uuid4()
        (player,) = players(1)
        connection, far = attach(hub, player)
        written: list[tuple[uuid.UUID, int, str]] = []
        hub.write_note = lambda g, s, a: written.append((g, s, a))  # type: ignore[method-assign]
        hub.ask(player, game, 4)
        await hub.receive(connection, '{"type": "note_answer", "answer": "yes"}')
        await hub.receive(connection, '{"type": "note_answer", "answer": "no"}')  # asked once
        await drain(connection)
        assert written == [(game, 4, "yes")]
        assert [m["type"] for m in far.sent] == ["lobby", "note_question", "error"]
        assert far.sent[1]["text"] == "Did you take notes during this game?"

    asyncio.run(scenario())


def test_leaving_or_playing_on_without_answering_is_unanswered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def scenario() -> None:
        hub, six = Writes(), players(6)
        conns = [attach(hub, p) for p in six]
        hub.ask(six[0], uuid.uuid4(), 0)
        hub.disconnect(conns[0][0])
        assert six[0].id not in hub.notes
        hub.ask(six[1], uuid.uuid4(), 1)
        for connection, _ in conns[1:]:
            await hub.receive(connection, '{"type": "join_queue"}')
        connection, _ = attach(hub, six[0])
        await hub.receive(connection, '{"type": "join_queue"}')  # the sixth: a table forms
        assert hub.notes == {}

        def broken(game: uuid.UUID, seat: int, answer: str) -> None:
            raise RuntimeError("database down")

        hub.write_note = broken  # type: ignore[method-assign]
        hub.ask(six[2], uuid.uuid4(), 2)
        await hub.receive(conns[2][0], '{"type": "note_answer", "answer": "no"}')
        await hub.close()

    asyncio.run(scenario())
    assert "a note answer could not be written" in capsys.readouterr().out
