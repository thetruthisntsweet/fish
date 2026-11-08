"""Rehearse the pilot on a deployed site (T4.2; docs/runbooks/rehearsal.md): six test players,
signed in as six accounts, play whole games together at a private room, the way people do.

    uv run python scripts/rehearse.py https://fish-pilot.thedefinitivesanjeevexperience.com \
        --sessions ~/rehearsal-sessions.txt --games 6

``--sessions`` is a file with six ``fish_session`` cookie values, one per line, from six
accounts signed in on that site. Each game, the first player makes a room and the other five
join it with its code. Every player answers every ping and, after a wait drawn from 0.8 to
4 seconds, makes a random legal move: an ask, an assignment, a choice or a vote. A player
presses Call on a random set after 4% of updates, or when it is their turn and they have no
ask left (R.8.3). A new update before the wait is over starts a new wait. In the game
``--drop-in`` (the 2nd; 0 for none), the sixth player closes their connection after ten
updates and stays away 40 seconds, so a bot takes their seat (R.8.4); they come back to be
told so. After each game everyone answers the note-taking question "no".

It prints each game's result and length, and, at the end, the median wait it chose for each
kind of decision: the pilot report's response times should be at least these, plus the round
trip. Exits 0 and prints PASS if every game ended by the rules, or 1 with what went wrong.
These games are real games on that site, started before the pilot, so the pilot's
``--since 2026-12-01`` leaves them out.
"""

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

PROTOCOL_VERSION = 3
PRESS_ODDS = 0.04
WAIT_S = (0.8, 4.0)
AWAY_S = 40
"""Longer than the 30 seconds after which a bot takes a seat (R.8.4)."""
GAME_LIMIT_S = 45 * 60
KIND_OF_PHASE = {
    "turn": "turn",
    "runout": "turn",
    "window": "press",
    "assign": "assign",
    "choose": "choice",
    "vote": "choice",
}


@dataclass
class Waits:
    """The waits the players chose, by kind of decision (fish_agents.delays.KINDS)."""

    by_kind: dict[str, list[float]] = field(
        default_factory=lambda: {k: [] for k in ("turn", "press", "assign", "choice")}
    )

    def lines(self) -> list[str]:
        out = ["Median wait chosen, seconds (the report's response times are at least these):"]
        for kind, waits in self.by_kind.items():
            median = f"{statistics.median(waits):.2f}" if waits else "-"
            out.append(f"  {kind:<8}{median:>6}  ({len(waits)} moves)")
        return out


class Player:
    """One test player's connection for one game."""

    def __init__(self, url: str, session: str, rng: random.Random, waits: Waits, speed: float):
        self.url, self.session, self.rng, self.waits, self.speed = url, session, rng, waits, speed
        self.ws: Any = None
        self.pending: asyncio.Task[None] | None = None
        self.over: dict[str, Any] | None = None
        self.updates = 0

    async def connect(self) -> None:
        self.ws = await websockets.connect(
            self.url, additional_headers={"Cookie": f"fish_session={self.session}"}
        )
        await self.send({"type": "client_hello", "protocol_version": PROTOCOL_VERSION})

    async def send(self, message: dict[str, object]) -> None:
        await self.ws.send(json.dumps(message))

    async def next(self, kind: str) -> dict[str, Any]:
        """The next message of ``kind``, answering pings and failing on errors meanwhile."""
        while True:
            message = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=60))
            if message["type"] == "ping":
                await self.send({"type": "pong", "nonce": message["nonce"]})
            elif message["type"] == "error":
                raise RuntimeError(f"the server said: {message['message']}")
            elif message["type"] == kind:
                return message

    async def _move(self, message: dict[str, Any], wait: float, kind: str) -> None:
        await asyncio.sleep(wait / self.speed)
        view = message["view"]
        seen = None if view["last_event"] is None else view["last_event"]["number"]
        if kind == "press":
            set_id = self.rng.choice(message["pressable"])
            await self.send({"type": "press", "set_id": set_id, "seen": seen})
        else:
            await self.send({"type": "act", "index": self.rng.choice(message["actions"])})
        self.waits.by_kind[kind].append(wait)

    def decide(self, message: dict[str, Any]) -> None:
        """A new update: drop any move still waiting, and maybe start a new one."""
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        view = message["view"]
        mine = view["phase"] == "turn" and view["current"] == view["seat"]
        must = mine and not message["actions"]
        if message["pressable"] and (must or self.rng.random() < PRESS_ODDS):
            kind = "press"
        elif message["actions"]:
            kind = KIND_OF_PHASE[view["phase"]]
        else:
            return
        wait = self.rng.uniform(*WAIT_S)
        self.pending = asyncio.create_task(self._move(message, wait, kind))

    async def play(self, drop_after: int | None = None) -> dict[str, Any] | None:
        """Play until the game is over and the note question is answered; return the last
        view. With ``drop_after``, go away after that many updates, come back after
        ``AWAY_S``, and return None once told a bot took the seat."""
        while True:
            message = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=120))
            match message["type"]:
                case "ping":
                    await self.send({"type": "pong", "nonce": message["nonce"]})
                case "update":
                    self.updates += 1
                    if message["view"]["phase"] == "over":
                        self.over = message["view"]
                    if drop_after is not None and self.updates >= drop_after:
                        return await self._away()
                    self.decide(message)
                case "note_question":
                    await self.send({"type": "note_answer", "answer": "no"})
                    return self.over
                case "error":
                    raise RuntimeError(f"the server said: {message['message']}")
                case _:
                    pass

    async def _away(self) -> None:
        if self.pending is not None:
            self.pending.cancel()
        await self.ws.close()
        print(f"  a player goes away for {AWAY_S} seconds")
        await asyncio.sleep(AWAY_S)  # at any speed: the server's 30 seconds are real
        await self.connect()
        while True:  # told that a bot took the seat, then shown the lobby
            message = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=60))
            if message["type"] == "ping":
                await self.send({"type": "pong", "nonce": message["nonce"]})
            elif message["type"] == "error" and "bot" in message["message"]:
                print(f"  ...back, and told: {message['message']}")
                return None
            elif message["type"] == "update":
                raise RuntimeError("back after 40 seconds, but still in the seat")

    async def close(self) -> None:
        if self.pending is not None:
            self.pending.cancel()
        if self.ws is not None:
            await self.ws.close()


async def one_game(
    url: str, sessions: list[str], rng: random.Random, waits: Waits, drop: bool, speed: float
) -> dict[str, Any]:
    players = [Player(url, s, random.Random(rng.random()), waits, speed) for s in sessions]
    try:
        for p in players:
            await p.connect()
            await p.next("lobby")
        await players[0].send({"type": "create_room"})
        code = (await players[0].next("lobby"))["code"]
        for p in players[1:]:
            await p.send({"type": "join_room", "code": code})
        plays = [p.play(10 if drop and n == 5 else None) for n, p in enumerate(players)]
        ends = await asyncio.wait_for(asyncio.gather(*plays), timeout=GAME_LIMIT_S)
    finally:
        for p in players:
            await p.close()
    views = [v for v in ends if v is not None]
    if not views:
        raise RuntimeError("nobody saw the game end")
    return views[0]


async def rehearse(
    base: str, sessions: list[str], games: int, drop_in: int, speed: float = 1.0
) -> Waits:
    url = base.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/ws"
    rng, waits = random.Random(), Waits()
    for n in range(1, games + 1):
        start = time.monotonic()
        view = await one_game(url, sessions, rng, waits, n == drop_in, speed)
        minutes = (time.monotonic() - start) / 60
        if view["outcome"] not in ("finished", "unfinished"):
            raise RuntimeError(f"game {n} did not end by the rules: {view['outcome']}")
        print(f"game {n}: {view['outcome']}, team {view['winner']} won, {minutes:.1f} minutes")
    return waits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse the pilot on a deployed site.")
    parser.add_argument("base", help="the site's address")
    parser.add_argument("--sessions", type=Path, required=True, help="six fish_session values")
    parser.add_argument("--games", type=int, default=6, help="how many games (6)")
    parser.add_argument(
        "--drop-in", type=int, default=2, help="the game a player leaves (2; 0: none)"
    )
    args = parser.parse_args(argv)
    sessions = [line.strip() for line in args.sessions.read_text().splitlines() if line.strip()]
    if len(sessions) != 6 or len(set(sessions)) != 6:
        parser.error(f"{args.sessions} needs six different session values, one per line")
    try:
        waits = asyncio.run(rehearse(args.base, sessions, args.games, args.drop_in))
    except (OSError, TimeoutError, RuntimeError, websockets.ConnectionClosed) as problem:
        print(f"FAIL: {type(problem).__name__}: {problem}")
        return 1
    print("\n".join(waits.lines()))
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
