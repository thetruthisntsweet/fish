"""Check a deployed server the way a player reaches it (T3.1, T3.3, T3.6): the website,
health, its database, sign-in, the game socket.

Sign in first in a browser (the emailed link, then the button), then copy the value of the
``fish_session`` cookie from the browser's developer tools (Application, or Storage, then
Cookies). Then:

    uv run python scripts/try_server.py https://fish-pilot.thedefinitivesanjeevexperience.com \
        --session <cookie value>

It checks that ``/`` serves the web client and ``/study`` names the text the site shows,
that ``/health`` reports protocol 3, that ``/health/db`` reaches the database and finds it
at this checkout's newest migration (so run it from an up-to-date main), that ``/auth/me``
says signed in and allowed to play (the study information accepted, not withdrawn), and over
``/ws`` that the server says hello, shows the lobby, makes a room and leaves it. Exits 0
and prints PASS, or 1 with what failed. It never joins the solo queue, so it cannot start a
game.
"""

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

import websockets
from alembic.config import Config
from alembic.script import ScriptDirectory

PROTOCOL_VERSION = 3
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def get(url: str, session: str | None = None) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url, headers={"Cookie": f"fish_session={session}"} if session else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def newest_migration() -> str:
    """The newest migration in this checkout, which a finished deploy of it is at."""
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    if head is None:
        raise RuntimeError(f"no migrations found from {ALEMBIC_INI}")
    return head


def check_health(base: str) -> None:
    """``/health`` is up and speaks this protocol; ``/health/db`` reaches the database and
    finds it at the newest migration. Raises RuntimeError saying what is wrong."""
    status, health = get(f"{base}/health")
    print("health:", status, health)
    if status != 200 or health.get("protocol_version") != PROTOCOL_VERSION:
        raise RuntimeError(f"/health should report protocol {PROTOCOL_VERSION}")
    status, database = get(f"{base}/health/db")
    print("db:    ", status, database)
    if status != 200 or database.get("database") != "ok":
        raise RuntimeError("/health/db: the server cannot reach its database")
    newest = newest_migration()
    if database.get("schema_revision") != newest:
        raise RuntimeError(
            f"/health/db: the database is at {database.get('schema_revision')}, this checkout's "
            f"newest migration is {newest}: has the deploy finished, and is this main?"
        )


def page(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode()


async def socket(base: str, session: str) -> None:
    url = base.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    async with websockets.connect(
        url, additional_headers={"Cookie": f"fish_session={session}"}
    ) as ws:

        async def next_message(kind: str) -> dict[str, object]:
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if message["type"] == "ping":
                    await ws.send(json.dumps({"type": "pong", "nonce": message["nonce"]}))
                elif message["type"] == "error":
                    raise RuntimeError(f"the server said: {message}")
                elif message["type"] == kind:
                    return message

        await ws.send(json.dumps({"type": "client_hello", "protocol_version": PROTOCOL_VERSION}))
        print("hello:", await next_message("server_hello"))
        print("lobby:", await next_message("lobby"))
        await ws.send(json.dumps({"type": "create_room"}))
        room = await next_message("lobby")
        print("room: ", room)
        if room["waiting"] != "group" or not room["code"]:
            raise RuntimeError("no room was made")
        await ws.send(json.dumps({"type": "leave"}))
        left = await next_message("lobby")
        print("left: ", left)
        if left["waiting"] is not None:
            raise RuntimeError("still waiting after leaving")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a deployed Fish server end to end.")
    parser.add_argument(
        "base",
        help="the site's address, e.g. https://fish-pilot.thedefinitivesanjeevexperience.com",
    )
    parser.add_argument("--session", required=True, help="the fish_session cookie's value")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    try:
        if 'id="root"' not in page(f"{base}/"):
            raise RuntimeError("/ does not serve the web client")
        print("page:   the web client")
        status, study = get(f"{base}/study")
        print("study: ", status, study)
        if status != 200 or not study.get("version"):
            raise RuntimeError("/study should name the text this site shows")
        check_health(base)
        status, me = get(f"{base}/auth/me", args.session)
        print("me:    ", status, me)
        if me.get("signed_in") is not True:
            raise RuntimeError("that session does not sign in: sign in again, copy the cookie")
        study = cast(dict[str, object], me["study"])
        if not study["may_play"]:
            raise RuntimeError(f"this player may not play yet: {study}")
        asyncio.run(socket(base, args.session))
    except Exception as problem:  # one line, whatever went wrong
        print(f"FAIL: {problem}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
