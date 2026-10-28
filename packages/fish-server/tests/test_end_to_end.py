"""The website end to end (T3.1, T3.2): the real server on a real port, and people who reach it
the way a browser does. Each accepts the consent screen and asks for a sign-in link over
HTTP, uses the link, and connects over a real WebSocket with the session cookie. Six of them
are matched by the solo queue and play a whole game until the rules end it, answering every
ping and then the note-taking question; the corpus export reads the game back from the
database as a ``fish-corpus-v2`` record that replays to the same end, with every seat's
consent flags and note. Then one of them withdraws on the website, and the next export leaves
the game out. A second test stops the server in the middle of a game, as a deploy does, and
each player's connection closes with 1012 (service restart), and the game ends
``abandoned``. Takes about fifteen seconds of real time,
mostly declaration windows. Skipped without FISH_TEST_DATABASE_URL."""

import asyncio
import json
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import uvicorn
import websockets
from sqlalchemy import Engine, create_engine, func, pool, select

from fish_rules.corpus import SeatConsent, analysis_flags, read_corpus_record, response_times
from fish_server import db
from fish_server.app import app as server
from fish_server.auth import COOKIE, limiter
from fish_server.corpus_export import export
from fish_server.mailer import MemoryMailer, mailer
from fish_server.protocol import PROTOCOL_VERSION
from fish_server.settings import COHORT_SEED_VAR, CONSENT_VERSION_VAR, database_url

PRESS_ODDS = 0.04
"""A scripted player presses Call on a random set after this share of updates, besides
pressing when it must (its turn, and no ask left)."""

ACCEPTANCE = {
    "version": "v1.0",
    "us_resident_adult": True,
    "agrees": True,
    "no_outside_communication": True,
}

type Site = tuple[str, Callable[[], None], MemoryMailer]


@pytest.fixture
def app(server_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    monkeypatch.setenv(COHORT_SEED_VAR, "99")
    monkeypatch.delenv(CONSENT_VERSION_VAR, raising=False)
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def site(app: Engine) -> Iterator[Site]:
    """The server, running for real on a free local port, its sign-in emails kept: its
    address, a way to stop it as a deploy does, and the emails."""
    mail = MemoryMailer()
    server.dependency_overrides[mailer] = lambda: mail
    limiter._seen.clear()  # pyright: ignore[reportPrivateUsage]
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

    def stop() -> None:
        running.should_exit = True
        thread.join(20)
        assert not thread.is_alive(), "the server did not stop"

    yield f"127.0.0.1:{free}", stop, mail
    stop()
    server.dependency_overrides.clear()


# ---------------------------------------------------------------- a browser, by hand


class _Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # keep the 303 and its cookie


def http(
    method: str, url: str, body: bytes | None = None, *, cookie: str | None = None,
    json_body: bool = True,
) -> tuple[int, dict[str, str], bytes]:  # fmt: skip
    headers = {"content-type": "application/json" if json_body else
               "application/x-www-form-urlencoded"}  # fmt: skip
    if cookie:
        headers["cookie"] = f"{COOKIE}={cookie}"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.build_opener(_Stay).open(request, timeout=15) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as answer:
        with answer:
            return answer.code, dict(answer.headers), answer.read()


def sign_up(app: Engine, site: Site, count: int) -> list[tuple[uuid.UUID, str]]:
    """``count`` people outside the cohort, each having accepted the consent screen, asked
    for a link with it, and used the link: their player ids and session cookies."""
    where, _, mail = site
    people: list[tuple[uuid.UUID, str]] = []
    n = 0
    while len(people) < count:
        email = f"e2e{n}-{uuid.uuid4().hex[:6]}@example.org"
        n += 1
        body = json.dumps({"email": email, "consent": ACCEPTANCE}).encode()
        assert http("POST", f"http://{where}/auth/link", body)[0] == 202
        token = re.search(r"token=([A-Za-z0-9_\-]+)", mail.sent[-1]["text"])
        assert token is not None
        status, headers, _ = http(
            "POST", f"http://{where}/auth/verify", f"token={token.group(1)}".encode(),
            json_body=False,
        )  # fmt: skip
        assert status == 303
        cookie = re.search(rf"{COOKIE}=([^;]+)", headers["set-cookie"])
        assert cookie is not None
        with app.connect() as conn:
            player, cohort = conn.execute(
                select(db.players.c.player_id, db.players.c.cohort)
                .join(db.player_contacts)
                .where(db.player_contacts.c.email == email)
            ).one()
        if not cohort:  # keep to one queue
            people.append((player, cookie.group(1)))
    return people


# ---------------------------------------------------------------- players


async def player_until(ws: Any, rng: random.Random, moves: int) -> dict[str, Any]:
    """Play the first ``moves`` updates, then only answer pings until the connection closes."""
    await ws.send(json.dumps({"type": "client_hello", "protocol_version": PROTOCOL_VERSION}))
    await ws.send(json.dumps({"type": "join_queue"}))
    updates = 0
    async for raw in ws:
        message = json.loads(raw)
        if message["type"] == "ping":
            await ws.send(json.dumps({"type": "pong", "nonce": message["nonce"]}))
        elif message["type"] == "update":
            updates += 1
            if updates <= moves and message["actions"]:
                act = {"type": "act", "index": rng.choice(message["actions"])}
                await ws.send(json.dumps(act))
    raise AssertionError("the connection closed without a code")


async def player(
    where: str, token: str, rng: random.Random, *, until_moves: int | None = None
) -> dict[str, Any]:
    """Play until the game is over and answer the note-taking question, returning the last
    view with the answer as ``note``. With ``until_moves``, stop playing once that many
    updates have come and wait for the server to go: return the close code it sends."""
    over: dict[str, Any] | None = None
    url = f"ws://{where}/ws"
    async with websockets.connect(url, additional_headers={"Cookie": f"{COOKIE}={token}"}) as ws:
        if until_moves is not None:
            try:
                return await player_until(ws, rng, until_moves)
            except websockets.ConnectionClosed as closed:
                return {"code": None if closed.rcvd is None else closed.rcvd.code}
        await ws.send(json.dumps({"type": "client_hello", "protocol_version": PROTOCOL_VERSION}))
        await ws.send(json.dumps({"type": "join_queue"}))
        async for raw in ws:
            message = json.loads(raw)
            match message["type"]:
                case "ping":
                    await ws.send(json.dumps({"type": "pong", "nonce": message["nonce"]}))
                case "note_question":  # after the game (docs/corpus.md §4.2)
                    answer = rng.choice(["no", "declined"])
                    await ws.send(json.dumps({"type": "note_answer", "answer": answer}))
                    assert over is not None
                    return over | {"note": answer}
                case "update":
                    view = message["view"]
                    if view["phase"] == "over":
                        over = view
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
    raise AssertionError("the connection closed first")


def wait_for(
    app: Engine, table: Any, count: int, *, at_least: bool = False, **where: object
) -> None:
    deadline = time.monotonic() + 15
    while True:
        query = select(func.count()).select_from(table)
        for column, value in where.items():
            query = query.where(table.c[column] == value)
        with app.connect() as conn:
            found = conn.execute(query).scalar_one()
            if found == count or (at_least and found >= count):
                return
        assert time.monotonic() < deadline, f"{table.name}: never {count} rows"
        time.sleep(0.1)


# ---------------------------------------------------------------- the tests


def test_a_whole_game_from_consent_to_the_corpus_and_out_again(app: Engine, site: Site) -> None:
    where = site[0]
    people = sign_up(app, site, 6)

    async def everyone() -> list[dict[str, Any]]:
        games = [player(where, token, random.Random(n)) for n, (_, token) in enumerate(people)]
        return await asyncio.wait_for(asyncio.gather(*games), timeout=180)

    views = asyncio.run(everyone())
    assert sorted(v["seat"] for v in views) == list(range(6))
    assert len({(v["outcome"], v["winner"]) for v in views}) == 1  # one end, seen by all
    wait_for(app, db.game_endings, 1)
    wait_for(app, db.note_answers, 6)  # the answers are written as they come

    with app.connect() as conn:
        records, summary = export(conn)
        actions = conn.execute(select(func.count()).select_from(db.actions)).scalar_one()
    assert (summary.games, summary.exported) == (1, 1)
    game = read_corpus_record(records[0])
    assert len(game.steps) == actions
    assert str(game.final.outcome) == views[0]["outcome"] == game.game.completion
    assert game.final.winner() == views[0]["winner"]
    assert all(s.consent == SeatConsent("v1.0", True, True, True) for s in game.seats)
    flags = analysis_flags(game)
    assert flags.completed
    assert flags.solo
    assert not flags.bot_seat  # everyone acted in time
    assert {row.type for row in game.log} >= {"connection", "rtt"}
    notes = {v["seat"]: v["note"] for v in views}
    assert [s.note for s in game.seats] == [notes[seat] for seat in range(6)]
    assert flags.note_missing == ("declined" in notes.values())
    times = [t for t in response_times(game) if t is not None]
    assert times
    assert all(t > -1_000_000 for t in times)  # a person's response times, from the log

    _, cookie = people[3]
    status, _, _ = http("POST", f"http://{where}/withdraw", b'{"confirm": true}', cookie=cookie)
    assert status == 204
    with app.connect() as conn:
        records, summary = export(conn)
    assert (records, summary.withdrawn) == ([], 1)  # the whole game, every seat, leaves


def test_a_restart_in_the_middle_of_a_game_abandons_it(app: Engine, site: Site) -> None:
    where, stop, _ = site
    people = sign_up(app, site, 6)

    async def everyone() -> list[dict[str, Any]]:
        games = [
            asyncio.create_task(player(where, token, random.Random(n), until_moves=4))
            for n, (_, token) in enumerate(people)
        ]
        await asyncio.to_thread(lambda: wait_for(app, db.actions, 1, at_least=True))  # under way
        await asyncio.to_thread(stop)  # as a deploy does
        return await asyncio.wait_for(asyncio.gather(*games), timeout=30)

    closed = asyncio.run(everyone())
    assert {m["code"] for m in closed} == {1012}  # "service restart", which the client shows
    with app.connect() as conn:
        (completion,) = conn.execute(select(db.game_endings.c.completion)).scalars()
        records, summary = export(conn)
    assert completion == "abandoned"
    assert (records, summary.abandoned) == ([], 1)
