"""What the server writes to its logs (T3.8; Terms and Privacy §2, §4).

Render keeps the server's output for 7 days, and the privacy policy says it holds no IP
addresses, email addresses or sign-in links. So:

- Uvicorn's own access log is off (``--no-access-log`` in the Dockerfile): it names each
  visitor's address (the real one, behind Render's proxy) and the whole URL, which for a
  sign-in link is ``/sign-in?token=...``. ``AccessLog`` logs each request instead, by method,
  path (never the query string), status and time taken.
- Every line the server logs, through any logger, passes through ``Scrubbed``, which replaces
  anything shaped like an email address, an IP address or a token in a URL. That covers what
  the server's own lines would never say but an error's message might: a database error, for
  instance, can quote the row it was writing. (The database engine also leaves values out of
  its errors: ``hide_parameters``, ``fish_server.database``.)
- The server's own messages go to the ``fish_server`` logger, not ``print``.

``install()`` sets this up. The app calls it when it starts, after uvicorn has configured
its loggers, so their output is scrubbed too.
"""

import logging
import re
import sys
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, Final

LOGGER: Final = logging.getLogger("fish_server")
"""The server's own messages: errors in games, the sweep for stopped games."""

ACCESS: Final = logging.getLogger("fish_server.access")
"""One line per request: ``GET /information 200 3 ms``."""

UVICORN_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")

EMAIL: Final = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
IPV4: Final = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6: Final = re.compile(
    r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?:%\w+)?(?![\w:.])"
)
TOKEN: Final = re.compile(r"(?i)\b(token|code|key|session)=[^\s&;\"'<>]+")


def scrub(text: str) -> str:
    """``text`` with email addresses, IP addresses and URL tokens replaced."""
    text = TOKEN.sub(r"\1=[hidden]", text)
    text = EMAIL.sub("[email]", text)
    text = IPV4.sub("[address]", text)
    return IPV6.sub(_ipv6, text)


def _ipv6(match: re.Match[str]) -> str:
    """An IPv6 address, but not a clock time such as 12:30:05: two colons or fewer, no
    ``::`` and no hex letters."""
    found = match.group(0)
    if found.count(":") < 3 and "::" not in found and not re.search(r"[A-Fa-f]", found):
        return found
    return "[address]"


class Scrubbed(logging.Formatter):
    """Another formatter's lines, scrubbed: the message, and any traceback with it."""

    def __init__(self, inner: logging.Formatter | None = None) -> None:
        super().__init__()
        self.inner = inner or logging.Formatter("%(levelname)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return scrub(self.inner.format(record))


def install() -> None:
    """Scrub every handler of uvicorn's loggers and the root logger, and give the root logger
    one to standard output if it has none; the server's own logger logs from INFO and passes
    its lines up to it. Safe to call more than once."""
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stdout))
    for name in (*UVICORN_LOGGERS, ""):
        for handler in logging.getLogger(name).handlers:
            if not isinstance(handler.formatter, Scrubbed):
                handler.setFormatter(Scrubbed(handler.formatter))
    LOGGER.setLevel(logging.INFO)


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class AccessLog:
    """ASGI middleware: one line per request or WebSocket, when it ends, by method (or
    ``WebSocket``), path, status (101 for an accepted WebSocket; ``-`` if none was sent) and
    time taken. Never the client's address, the query string or any header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status: int | None = None

        async def sending(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            elif message["type"] == "websocket.accept":
                status = 101
            elif message["type"] == "websocket.close" and status is None:
                status = 403  # refused before it was accepted
            await send(message)

        try:
            await self.app(scope, receive, sending)
        finally:
            took = round((time.perf_counter() - started) * 1000)
            method = "WebSocket" if scope["type"] == "websocket" else scope["method"]
            shown = "-" if status is None else str(status)
            ACCESS.info("%s %s %s %d ms", method, scope["path"], shown, took)
