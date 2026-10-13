"""The Fish game server (T2.1 subtask 12: health check and WebSocket echo only).

Game logic arrives in T3.1. Until then the server proves the deployment works end to end:
``GET /health`` for the hosting platform's health checks, and ``/ws/echo`` to show that
long-lived WebSocket connections survive the platform's proxy (T2.1 §10, §17).

Run locally:  uv run uvicorn fish_server.app:app --reload
"""

from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION
from fish_server import __version__
from fish_server.protocol import PROTOCOL_VERSION, server_hello

app = FastAPI(title="Fish server", version=__version__, docs_url=None, redoc_url=None)


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
