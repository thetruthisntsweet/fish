"""Messages between the game server and its clients (T2.1 subtask 8).

These Pydantic models are the single source of truth for everything sent over the
WebSocket. ``fish_server.schema_export`` turns them into JSON Schema in ``schemas/``,
and ``scripts/gen_types.sh`` turns those into TypeScript in ``client/src/generated/``.
Never hand-write a message type on the client.

Every message has a ``type`` field naming it, so a receiver can tell messages apart.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION

PROTOCOL_VERSION = 1
"""Version of the message format. Bumped whenever a message changes shape."""


class Message(BaseModel):
    """Base for every message: immutable, and unknown fields are an error, not ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ClientHello(Message):
    """First message from a client after the WebSocket opens."""

    type: Literal["client_hello"]
    protocol_version: int = Field(ge=1, description="PROTOCOL_VERSION the client was built with.")


class ServerHello(Message):
    """The server's reply to ClientHello: which versions this server runs."""

    type: Literal["server_hello"]
    protocol_version: int = Field(ge=1, description="PROTOCOL_VERSION the server speaks.")
    ruleset_version: str = Field(description="Canonical Ruleset version, e.g. '1.0'.")
    rng_algorithm: str = Field(description="fish_rules.rng.RNG_ALGORITHM.")


CLIENT_MESSAGES: tuple[type[Message], ...] = (ClientHello,)
"""Messages a client sends to the server."""

SERVER_MESSAGES: tuple[type[Message], ...] = (ServerHello,)
"""Messages the server sends to a client."""


def server_hello() -> ServerHello:
    """The ServerHello this server sends, filled from the versions it actually runs."""
    return ServerHello(
        type="server_hello",
        protocol_version=PROTOCOL_VERSION,
        ruleset_version=RULESET_VERSION,
        rng_algorithm=RNG_ALGORITHM,
    )
