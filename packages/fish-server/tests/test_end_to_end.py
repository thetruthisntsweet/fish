"""The website end to end (T3.1, T3.2): the real server on a real port, and people who reach it
the way a browser does. Each accepts the consent screen and asks for a sign-in link over
HTTP, uses the link, and connects over a real WebSocket with the session cookie. Six of them
are matched by the solo queue and play a whole game until the rules end it, answering every
ping and then the note-taking question; the corpus export reads the game back from the
database as a ``fish-corpus-v2`` record that replays to the same end, with every seat's
consent flags and note. Then one of them withdraws on the website, and the next export leaves
the game out. A second test stops the server in the middle of a game, as a deploy does, and
each player's connection closes with 1012 (service restart), and the game ends
``abandoned``. A third has one person leave early: B1 takes their seat and the game is
recorded with the handover, the bot's waits and actions. A fourth has all six press Call at
once: one window, and the R.8.1 priority order decides the call. The whole games take a few
tens of seconds of real time, mostly declaration windows and bot waits. Skipped without
FISH_TEST_DATABASE_URL."""

import asyncio
import contextlib
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

from fish_rules.action_index import encode
from fish_rules.cards import SEATS, Seat, set_of, team_of
from fish_rules.codec import action_from_data
from fish_rules.corpus import SeatConsent, analysis_flags, read_corpus_record, response_times
from fish_rules.engine import replay
from fish_rules.events import Ask, Declare, OpenWindow
from fish_rules.priority import first_in_priority, priority_order
from fish_rules.state import new_game
from fish_server import db, table
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
    "terms_version": "v1.0",
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


async def leaver(where: str, token: str, rng: random.Random, moves: int) -> dict[str, Any]:
    """Play like everyone else for ``moves`` updates, then close the connection and never come
    back: after 30 seconds, B1 takes the seat (R.8.4). Returns the last view seen."""
    url = f"ws://{where}/ws"
    last: dict[str, Any] = {}
    async with websockets.connect(url, additional_headers={"Cookie": f"{COOKIE}={token}"}) as ws:
        await ws.send(json.dumps({"type": "client_hello", "protocol_version": PROTOCOL_VERSION}))
        await ws.send(json.dumps({"type": "join_queue"}))
        updates = 0
        async for raw in ws:
            message = json.loads(raw)
            if message["type"] == "ping":
                await ws.send(json.dumps({"type": "pong", "nonce": message["nonce"]}))
            elif message["type"] == "update":
                last = message["view"]
                updates += 1
                if updates > moves:
                    return last
                if message["actions"]:
                    act = {"type": "act", "index": rng.choice(message["actions"])}
                    await ws.send(json.dumps(act))
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


def test_a_person_who_leaves_is_replaced_by_b1_and_the_game_is_recorded_so(
    app: Engine, site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R.8.4, R.8.8: one person leaves early; after the reconnection time B1, remembering the
    latest 8 events, plays their seat with its waits, and the other five finish the game. The
    export has the handover, the bot's waits and its actions, and the five notes."""
    monkeypatch.setattr(table, "RECONNECT_US", 2 * table.SECOND_US)  # 30 seconds, made 2 here
    where = site[0]
    people = sign_up(app, site, 6)

    async def everyone() -> list[dict[str, Any]]:
        stay = [player(where, token, random.Random(n)) for n, (_, token) in enumerate(people[1:])]
        leave = leaver(where, people[0][1], random.Random(99), moves=6)
        return await asyncio.wait_for(asyncio.gather(leave, *stay), timeout=240)

    left, *views = asyncio.run(everyone())
    assert len({(v["outcome"], v["winner"]) for v in views}) == 1
    wait_for(app, db.game_endings, 1)
    wait_for(app, db.note_answers, 5)  # the person who left is not asked

    with app.connect() as conn:
        records, summary = export(conn)
    assert (summary.games, summary.exported) == (1, 1)
    game = read_corpus_record(records[0])
    seat = left["seat"]
    assert game.game.completion in ("finished", "unfinished")
    (handover,) = [row for row in game.log if row.type == "handover"]
    assert handover.seat == seat
    assert handover.fields == {"reason": "disconnect", "agent": "b1-v1", "memory": "last-k",
                               "k": 8}  # fmt: skip
    after = game.handover_after(seat)
    assert after is not None
    bot_steps = [i for i, step in enumerate(game.steps) if i >= after and step.seat == seat]
    assert bot_steps, "B1 never acted"
    waits = [row for row in game.log if row.type == "bot_delay"]
    assert {row.seat for row in waits} == {seat}
    taken = {row.after for row in waits if not row.fields["dropped"]}
    for i in bot_steps:  # each came after a wait: a press's Declare follows its OpenWindow
        assert i in taken or (isinstance(game.steps[i].action, Declare) and i - 1 in taken), i
    assert all(1_500_000 <= int(str(row.fields["delay_us"])) <= 4_000_000 for row in waits)
    assert game.seats[seat].note == "unanswered"  # a bot had the seat: not asked
    assert sum(s.note in ("no", "declined") for s in game.seats) == 5
    flags = analysis_flags(game)
    assert flags.completed
    assert flags.bot_seat  # in RQ1's sensitivity set only (corpus.md §6)
    assert not flags.primary


# ---------------------------------------------------------------- calls at once (T3.6)


class Client:
    """One person's socket, read in the background: pings are answered at once and every other
    message is queued for the test."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.updates: list[dict[str, Any]] = []
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        with contextlib.suppress(websockets.ConnectionClosed):
            async for raw in self.ws:
                message = json.loads(raw)
                if message["type"] == "ping":
                    await self.ws.send(json.dumps({"type": "pong", "nonce": message["nonce"]}))
                    continue
                if message["type"] == "update":
                    self.updates.append(message)
                await self.inbox.put(message)

    async def send(self, message: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(message))

    async def next(self, kind: str) -> dict[str, Any]:
        """The next message of type ``kind``, passing over the others."""
        while True:
            message = await asyncio.wait_for(self.inbox.get(), timeout=10)
            if message["type"] == kind:
                return message

    async def until(self, check: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        """The next update ``check`` accepts."""
        while not check(update := await self.next("update")):
            pass
        return update


async def seated(where: str, people: list[tuple[uuid.UUID, str]]) -> dict[Seat, Client]:
    """The six connected and matched by the solo queue: each one's client, by seat."""
    clients: list[Client] = []
    for _, token in people:
        ws = await websockets.connect(
            f"ws://{where}/ws", additional_headers={"Cookie": f"{COOKIE}={token}"}
        )
        client = Client(ws)
        await client.send({"type": "client_hello", "protocol_version": PROTOCOL_VERSION})
        await client.send({"type": "join_queue"})
        clients.append(client)
    firsts = [await c.next("update") for c in clients]
    return {u["view"]["seat"]: c for u, c in zip(firsts, clients, strict=True)}


def test_six_presses_at_once_open_one_window_and_r8_1_picks_the_call(
    app: Engine, site: Site
) -> None:
    """R.8.1, R.8.3, R.8.7 over real sockets. The current player makes an ask that succeeds;
    a player whose press has not seen it, naming the set of the card it moved, is told the
    press is stale. Then all six press Call on another set in the same instant: one window
    opens, every press is a declaration, and nobody is shown another's; an ask sent while the
    window is open is discarded and its sender told; when the window closes the call that
    proceeds is the first of the six in the window's R.8.1 priority order. The actions written
    replay to that same call."""
    where = site[0]
    people = sign_up(app, site, 6)
    with_seed: list[int] = []

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], int, dict[Seat, Client]]:
        seat = await seated(where, people)
        with app.connect() as conn:
            seed = int(conn.execute(select(db.games.c.seed)).scalar_one())
        with_seed.append(seed)
        state = new_game(seed)
        turn = state.current
        assert turn is not None

        # An ask certain to succeed (the test knows the deal), so it moves a card.
        held = {set_of(c) for c in state.hands[turn]}
        target, card = next(
            (s, c) for s in SEATS if team_of(s) != team_of(turn)
            for c in state.hands[s] if set_of(c) in held
        )  # fmt: skip
        await seat[turn].send({"type": "act", "index": encode(Ask(turn, target, card))})
        asked = [
            await c.until(lambda u: u["view"]["last_event"] is not None) for c in seat.values()
        ]
        (event,) = {json.dumps(u["view"]["last_event"]) for u in asked}  # the same for all
        assert json.loads(event)["success"]
        seen = json.loads(event)["number"]

        # R.8.7: a press that has not seen the ask, on the set of the card it moved.
        late = next(s for s in SEATS if s not in (turn, target))
        await seat[late].send({"type": "press", "set_id": set_of(card), "seen": None})
        stale = await seat[late].next("rejected")

        # Six presses at once on a set the ask did not touch, then an ask inside the window.
        named = next(s for s in range(9) if s != set_of(card))
        presses = [c.send({"type": "press", "set_id": named, "seen": seen}) for c in seat.values()]
        await asyncio.gather(*presses)
        other = next(c for c in state.hands[target] if c != card)
        await seat[turn].send({"type": "act", "index": encode(Ask(turn, target, other))})
        discarded = await seat[turn].next("rejected")
        for client in seat.values():
            await client.until(lambda u: u["view"]["phase"] == "assign")
        for client in seat.values():
            await client.ws.close()
            await client.reader
        return stale, discarded, named, seat

    stale, discarded, named, seat = asyncio.run(asyncio.wait_for(scenario(), timeout=60))
    (seed,) = with_seed
    assert (stale["reason"], stale["discarded"]) == ("stale", False)
    assert (discarded["reason"], discarded["discarded"]) == ("illegal", True)

    wait_for(app, db.server_log, 2, type="rejected")
    with app.connect() as conn:
        rows = conn.execute(select(db.actions.c.action).order_by(db.actions.c.seq)).scalars().all()
    actions = [action_from_data(row) for row in rows]
    assert sum(isinstance(a, OpenWindow) for a in actions) == 1  # one window for six presses
    declared = [a.seat for a in actions if isinstance(a, Declare)]
    assert sorted(declared) == list(SEATS)
    assert {a.set_id for a in actions if isinstance(a, Declare)} == {named}
    caller = first_in_priority(priority_order(seed, 0), declared)

    for s, client in seat.items():
        windows = [u["view"]["window"] for u in client.updates if u["view"]["window"] is not None]
        assert windows, f"seat {s} never saw the window"
        assert {w["own_declaration"] for w in windows} <= {None, named}  # its own, if any
        (assigning,) = [u for u in client.updates if u["view"]["phase"] == "assign"][:1]
        assert assigning["view"]["call"] == {"caller": caller, "set_id": named}  # R.8.1

    *_, (final, _) = replay(seed, actions)
    assert final.call is not None
    assert (final.call.caller, final.call.set_id) == (caller, named)
