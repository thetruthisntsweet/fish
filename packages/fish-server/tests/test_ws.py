"""The game over WebSockets (T3.1), on the real clock and a real database: signing in by
cookie, the hello, the lobby, six players matched into a game, updates to everyone after every
change, a window closed by its timer, round trips, disconnects, and the rows written as it
happens. Skipped without FISH_TEST_DATABASE_URL."""

import contextlib
import json
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, pool, select
from starlette.testclient import WebSocketTestSession

from fish_server import db
from fish_server.app import app as server
from fish_server.auth import COOKIE
from fish_server.consent import accept, withdraw
from fish_server.protocol import PROTOCOL_VERSION
from fish_server.settings import database_url
from fish_server.signin import player_for, start_session

type Socket = WebSocketTestSession
HELLO = {"type": "client_hello", "protocol_version": PROTOCOL_VERSION}


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


OPEN: list[contextlib.ExitStack] = []


@pytest.fixture
def http(app: Engine) -> Iterator[TestClient]:
    """The app with its hub running; every socket ``connect`` opens is closed afterwards,
    before the app stops."""
    with TestClient(server) as client, contextlib.ExitStack() as sockets:
        OPEN.append(sockets)
        yield client
        OPEN.pop()


def session(
    app: Engine, email: str, *, cohort_seed: int = 7, consented: bool = True
) -> tuple[uuid.UUID, str]:
    """A signed-in player, who has accepted the study information unless ``consented`` is
    False."""
    with app.begin() as conn:
        player = player_for(conn, email, cohort_seed=cohort_seed)
        if consented:
            accept(conn, player, "v1.0")
        return player, start_session(conn, player)


def cohort_of(app: Engine, player: uuid.UUID) -> bool:
    with app.connect() as conn:
        return conn.execute(
            select(db.players.c.cohort).where(db.players.c.player_id == player)
        ).scalar_one()


def until(socket: Socket, kind: str, *, answer_pings: bool = True) -> dict[str, Any]:
    """Read messages until one of type ``kind``; answers pings on the way."""
    while True:
        message: dict[str, Any] = socket.receive_json()
        if message["type"] == kind:
            return message
        if message["type"] == "ping" and answer_pings:
            socket.send_json({"type": "pong", "nonce": message["nonce"]})


def wait_for(check: Callable[[], bool], seconds: float = 5) -> None:
    end = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.05)


def count(app: Engine, table: Any, **where: object) -> int:
    query = select(func.count()).select_from(table)
    for column, value in where.items():
        query = query.where(table.c[column] == value)
    with app.connect() as conn:
        return conn.execute(query).scalar_one()


# ---------------------------------------------------------------- signing in and hello


def test_without_a_session_the_server_says_sign_in(http: TestClient) -> None:
    with http.websocket_connect("/ws") as socket:
        assert socket.receive_json()["code"] == "not_signed_in"
    with http.websocket_connect("/ws", headers={"cookie": f"{COOKIE}=nope"}) as socket:
        assert socket.receive_json()["code"] == "not_signed_in"


@pytest.mark.parametrize(
    "hello", [{"type": "client_hello", "protocol_version": 1}, {"type": "join_queue"}, "not json"]
)
def test_the_first_message_is_a_hello_for_this_protocol(
    http: TestClient, app: Engine, hello: object
) -> None:
    _, token = session(app, "a@example.org")
    with http.websocket_connect("/ws", headers={"cookie": f"{COOKIE}={token}"}) as socket:
        socket.send_text(hello if isinstance(hello, str) else json.dumps(hello))
        assert socket.receive_json()["code"] == "protocol_version"


def test_leaving_before_the_hello_is_fine(http: TestClient, app: Engine) -> None:
    _, token = session(app, "z@example.org")
    with http.websocket_connect("/ws", headers={"cookie": f"{COOKIE}={token}"}) as socket:
        time.sleep(0.5)  # signed in by now, waiting for the hello
        socket.close()


def connect(http: TestClient, token: str) -> Any:
    session = http.websocket_connect("/ws", headers={"cookie": f"{COOKIE}={token}"})
    entered = OPEN[-1].enter_context(session)
    entered.send_json(HELLO)
    assert entered.receive_json()["type"] == "server_hello"
    return entered


def test_the_lobby_and_what_does_not_fit_it(http: TestClient, app: Engine) -> None:
    _, token = session(app, "b@example.org")
    socket = connect(http, token)
    assert until(socket, "lobby") == {"type": "lobby", "waiting": None, "code": None, "people": 0}
    socket.send_json({"type": "press", "set_id": 0, "seen": None})
    assert until(socket, "error")["code"] == "not_now"  # no table
    socket.send_text("{")
    assert until(socket, "error")["code"] == "bad_message"
    socket.send_json(HELLO)
    assert until(socket, "error")["code"] == "not_now"
    socket.send_json({"type": "create_room"})
    room = until(socket, "lobby")
    assert (room["waiting"], room["people"]) == ("group", 1)
    socket.send_json({"type": "join_queue"})
    assert "already waiting" in until(socket, "error")["message"]
    socket.send_json({"type": "join_room", "code": "ZZZZZZ"})
    assert until(socket, "error")["code"] == "not_now"
    socket.send_json({"type": "leave"})
    assert until(socket, "lobby")["waiting"] is None
    socket.send_json({"type": "pong", "nonce": 1})  # nothing to answer, nothing said
    socket.send_json({"type": "join_queue"})
    assert until(socket, "lobby")["waiting"] == "solo"
    socket.close()


def test_only_those_who_may_play_wait_for_a_game(http: TestClient, app: Engine) -> None:
    """Consent Screen §2: the study information accepted first; never after withdrawing."""
    _, fresh = session(app, "g@example.org", consented=False)
    socket = connect(http, fresh)
    until(socket, "lobby")
    socket.send_json({"type": "join_queue"})
    assert until(socket, "error")["message"] == "Accept the study information first."
    gone, token = session(app, "h@example.org")
    with app.begin() as conn:
        withdraw(conn, gone, "website")
    other = connect(http, token)
    until(other, "lobby")
    other.send_json({"type": "create_room"})
    assert "withdrawn" in until(other, "error")["message"]
    other.send_json({"type": "leave"})  # leaving is always allowed
    assert until(other, "lobby")["waiting"] is None


def test_a_newer_connection_replaces_the_older(http: TestClient, app: Engine) -> None:
    _, token = session(app, "c@example.org")
    first = connect(http, token)
    until(first, "lobby")
    second = connect(http, token)
    assert until(first, "error")["message"].startswith("You opened Fish somewhere else")
    assert until(second, "lobby")["waiting"] is None
    second.close()


# ---------------------------------------------------------------- a game


def six(http: TestClient, app: Engine) -> tuple[list[Any], list[uuid.UUID]]:
    """Six players of one cohort side, connected and in the solo queue until seated."""
    players, sockets = [], []
    n = 0
    while len(players) < 6:
        player, token = session(app, f"p{n}@example.org")
        n += 1
        if cohort_of(app, player):
            continue  # keep to one queue
        players.append(player)
        sockets.append(connect(http, token))
        until(sockets[-1], "lobby")
    for socket in sockets:
        socket.send_json({"type": "join_queue"})
    return sockets, players


def test_six_players_play_and_every_step_is_written(http: TestClient, app: Engine) -> None:
    sockets, _ = six(http, app)
    updates = [until(s, "update") for s in sockets]
    assert sorted(u["view"]["seat"] for u in updates) == list(range(6))
    by_seat = {u["view"]["seat"]: s for u, s in zip(updates, sockets, strict=True)}
    first = next(u for u in updates if u["view"]["seat"] == u["view"]["current"])
    assert first["timers"][0]["name"] == "turn"
    (game_id,) = _games(app)
    assert count(app, db.seats, game_id=game_id) == 6

    current = by_seat[first["view"]["current"]]
    current.send_json({"type": "act", "index": first["actions"][0]})
    for socket in sockets:
        assert until(socket, "update")["view"]["last_event"]["type"] == "AskEvent"

    presser = by_seat[(first["view"]["current"] + 1) % 6]
    presser.send_json({"type": "press", "set_id": 0, "seen": 0})
    opened = [until(s, "update") for s in sockets]
    assert all(u["view"]["window"] is not None for u in opened)
    assert {u["timers"][0]["name"] for u in opened} == {"window"}
    closed = [until(s, "update") for s in sockets]  # the window timer, a second later
    assert all(u["view"]["phase"] in ("assign", "over") for u in closed)

    wait_for(lambda: count(app, db.actions, game_id=game_id) >= 4)
    with app.connect() as conn:
        rows = conn.execute(
            select(db.actions).where(db.actions.c.game_id == game_id).order_by(db.actions.c.seq)
        ).all()
    assert [r.action["type"] for r in rows[:4]] == ["Ask", "OpenWindow", "Declare", "CloseWindow"]
    assert rows[3].cause_timer == "window"
    assert rows[3].received_us - rows[1].received_us == 1_000_000  # R.8.3, R.8.5
    assert all(r.sent_us >= r.received_us for r in rows)
    wait_for(lambda: count(app, db.server_log, game_id=game_id, type="rtt") >= 1)
    assert count(app, db.server_log, game_id=game_id, type="connection") == 6

    presser.close()  # R.8.4: the seat's person is away
    wait_for(lambda: count(app, db.server_log, game_id=game_id, type="connection") == 7)
    for socket in sockets:
        if socket is not presser:
            socket.close()


def _games(app: Engine) -> list[uuid.UUID]:
    with app.connect() as conn:
        return list(conn.execute(select(db.games.c.game_id)).scalars())


def test_an_ending_is_written_once(app: Engine) -> None:
    from fish_server.game import Game
    from fish_server.games import start_game
    from fish_server.hub import Hub
    from fish_server.lobby import Formed, Player

    seated = [session(app, f"e{n}@example.org")[0] for n in range(6)]
    table = Formed(tuple(Player(p, False) for p in seated), "group", cohort_table=False)
    with app.begin() as conn:
        game_id = start_game(conn, table, seed=5, server_commit="t", started_at=datetime.now(UTC))
    Hub(lambda: app, "t").write_ending(Game(game_id, 5, seated), "abandoned")
    assert count(app, db.game_endings, game_id=game_id, completion="abandoned") == 1
