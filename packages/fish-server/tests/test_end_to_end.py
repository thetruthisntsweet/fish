"""A whole game end to end (T3.1): the real server on a real port, six scripted players
connecting over real WebSockets with their session cookies, matched by the solo queue, and
playing until the rules end the game, answering every ping. Then the corpus export reads the
game back from the database as a ``fish-corpus-v2`` record that replays to the same end. Takes
about ten seconds of real time, mostly declaration windows. Skipped without
FISH_TEST_DATABASE_URL."""

import asyncio
import json
import random
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
import websockets
from sqlalchemy import Engine, create_engine, func, insert, pool, select

from fish_rules.corpus import analysis_flags, read_corpus_record, response_times
from fish_server import db
from fish_server.app import app as server
from fish_server.auth import COOKIE
from fish_server.corpus_export import export
from fish_server.protocol import PROTOCOL_VERSION
from fish_server.settings import database_url
from fish_server.signin import player_for, start_session

PRESS_ODDS = 0.04
"""A scripted player presses Call on a random set after this share of updates, besides
pressing when it must (its turn, and no ask left)."""


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def port(app: Engine) -> Iterator[int]:
    """The server, running for real on a free local port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    config = uvicorn.Config(server, host="127.0.0.1", port=free, log_level="warning")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not running.started:
        assert time.monotonic() < deadline, "the server did not start"
        time.sleep(0.05)
    yield free
    running.should_exit = True
    thread.join(10)


def signed_in(app: Engine, count: int) -> list[tuple[uuid.UUID, str]]:
    """``count`` players outside the cohort, each with a session and an acceptance of the
    consent screen, so their seats get consent flags and their games enter the corpus."""
    out: list[tuple[uuid.UUID, str]] = []
    n = 0
    with app.begin() as conn:
        while len(out) < count:
            player = player_for(conn, f"e2e{n}@example.org", cohort_seed=99)
            n += 1
            cohort = conn.execute(
                select(db.players.c.cohort).where(db.players.c.player_id == player)
            ).scalar_one()
            if cohort:
                continue
            conn.execute(
                insert(db.consents).values(
                    player_id=player,
                    version="v1.0",
                    us_resident_adult=True,
                    agrees=True,
                    no_outside_communication=True,
                )
            )
            out.append((player, start_session(conn, player)))
    return out


async def player(port: int, token: str, rng: random.Random) -> dict[str, Any]:
    """Play until the game is over; returns the last view."""
    url = f"ws://127.0.0.1:{port}/ws"
    async with websockets.connect(url, additional_headers={"Cookie": f"{COOKIE}={token}"}) as ws:
        await ws.send(json.dumps({"type": "client_hello", "protocol_version": PROTOCOL_VERSION}))
        await ws.send(json.dumps({"type": "join_queue"}))
        async for raw in ws:
            message = json.loads(raw)
            match message["type"]:
                case "ping":
                    await ws.send(json.dumps({"type": "pong", "nonce": message["nonce"]}))
                case "update":
                    view = message["view"]
                    if view["phase"] == "over":
                        return view
                    seen = None if view["last_event"] is None else view["last_event"]["number"]
                    mine = view["phase"] == "turn" and view["current"] == view["seat"]
                    if message["pressable"] and (
                        (mine and not message["actions"]) or rng.random() < PRESS_ODDS
                    ):
                        press = {"type": "press", "seen": seen,
                                 "set_id": rng.choice(message["pressable"])}  # fmt: skip
                        await ws.send(json.dumps(press))
                    elif message["actions"]:
                        act = {"type": "act", "index": rng.choice(message["actions"])}
                        await ws.send(json.dumps(act))
                case "error":
                    raise AssertionError(message)
                case _:
                    pass
    raise AssertionError("the connection closed before the game ended")


def test_a_whole_game_from_sign_in_to_the_corpus(app: Engine, port: int) -> None:
    players = signed_in(app, 6)

    async def everyone() -> list[dict[str, Any]]:
        games = [player(port, token, random.Random(n)) for n, (_, token) in enumerate(players)]
        return await asyncio.wait_for(asyncio.gather(*games), timeout=180)

    views = asyncio.run(everyone())
    assert sorted(v["seat"] for v in views) == list(range(6))
    assert len({(v["outcome"], v["winner"]) for v in views}) == 1  # one end, seen by all

    deadline = time.monotonic() + 10
    while True:
        with app.connect() as conn:
            if conn.execute(select(func.count()).select_from(db.game_endings)).scalar():
                break
        assert time.monotonic() < deadline, "the ending was not written"
        time.sleep(0.1)

    with app.connect() as conn:
        records, summary = export(conn)
        actions = conn.execute(select(func.count()).select_from(db.actions)).scalar_one()
    assert (summary.games, summary.exported) == (1, 1)
    game = read_corpus_record(records[0])
    assert len(game.steps) == actions
    assert str(game.final.outcome) == views[0]["outcome"] == game.game.completion
    assert game.final.winner() == views[0]["winner"]
    flags = analysis_flags(game)
    assert flags.completed
    assert flags.solo
    assert not flags.bot_seat  # everyone acted in time
    assert {row.type for row in game.log} >= {"connection", "rtt"}
    times = [t for t in response_times(game) if t is not None]
    assert times
    assert all(t > -1_000_000 for t in times)  # a person's response times, from the log
