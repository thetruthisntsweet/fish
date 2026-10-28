"""The Fish game server (T2.1 subtasks 12-13; T3.1).

``GET /health`` for the hosting platform's health checks, ``GET /health/db`` to confirm the
database is reachable and migrated, and ``/ws/echo`` to show that long-lived WebSocket
connections survive the platform's proxy (T2.1 §10, §17). Signing in by emailed link is in
``fish_server.auth``.

Run locally:  uv run uvicorn fish_server.app:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION
from fish_server import __version__, auth
from fish_server.database import dispose_engine, get_engine, schema_revision
from fish_server.protocol import PROTOCOL_VERSION, server_hello


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Runs around the server's whole life: on shutdown, close database connections."""
    yield
    dispose_engine()


app = FastAPI(
    title="Fish server", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
)
app.include_router(auth.router)


class Health(BaseModel):
    """What ``/health`` reports: that the server is up, and exactly what it runs."""

    status: Literal["ok"]
    server_version: str
    ruleset_version: str
    rng_algorithm: str
    protocol_version: int


@app.get("/health")
def health() -> Health:
    """Liveness check for the hosting platform. Deliberately touches no database: a
    database outage should not make the platform restart a server that is otherwise fine."""
    return Health(
        status="ok",
        server_version=__version__,
        ruleset_version=RULESET_VERSION,
        rng_algorithm=RNG_ALGORITHM,
        protocol_version=PROTOCOL_VERSION,
    )


class DatabaseHealth(BaseModel):
    """What ``/health/db`` reports. Never includes error details: they can contain hostnames."""

    database: Literal["ok", "unavailable"]
    schema_revision: str | None


@app.get("/health/db")
def health_db(response: Response) -> DatabaseHealth:
    """Is the database reachable, and which migration is it at? 503 if unreachable.

    Separate from ``/health`` on purpose: Render's health check must not restart a working
    server because of a database problem.
    """
    try:
        revision = schema_revision(get_engine())
    except SQLAlchemyError, RuntimeError:
        response.status_code = 503
        return DatabaseHealth(database="unavailable", schema_revision=None)
    return DatabaseHealth(database="ok", schema_revision=revision)


@app.websocket("/ws/echo")
async def ws_echo(websocket: WebSocket) -> None:
    """Send ServerHello, then echo every text message back until the client leaves.

    Keepalive pings are sent by uvicorn itself (``--ws-ping-interval``), so idle
    connections are not dropped by proxies along the way.
    """
    await websocket.accept()
    await websocket.send_text(server_hello().model_dump_json())
    try:
        while True:
            await websocket.send_text(await websocket.receive_text())
    except WebSocketDisconnect:
        return
