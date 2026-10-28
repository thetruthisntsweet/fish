"""Writing a new table to the database (T3.1; docs/corpus.md §2 to §4).

When matchmaking forms a table (``fish_server.lobby``), ``start_game`` writes its ``games``
row (the seed, the versions it is played under, the code that runs it, how it was formed),
one ``seats`` row per seat, and for each person their seat's consent flags, copied from their
latest acceptance (``seat_consents``; Consent Screen §3), before the first action. A person
with no acceptance gets no flags, and the game cannot enter the corpus. All three tables are
append-only: what a game was set up as never changes. Actions and server log rows follow as
the game is played (the game loop); its ending, when the rules end it.
"""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import Connection, insert, select

from fish_rules.codec import ACTION_ENCODING
from fish_rules.state import STATE_ENCODING
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.lobby import Formed, Player
from fish_server.protocol import PROTOCOL_VERSION


def new_seed() -> int:
    """A game seed: 64 bits from the operating system, so nobody can predict a deal."""
    return secrets.randbits(64)


def start_game(
    conn: Connection, table: Formed, *, seed: int, server_commit: str, started_at: datetime
) -> uuid.UUID:
    """Write ``table``'s game and seats; returns the new game's id."""
    game = uuid.uuid4()
    conn.execute(
        insert(db.games).values(
            game_id=game,
            seed=seed,
            ruleset=RULESET_VERSION,
            action_encoding=ACTION_ENCODING,
            state_encoding=STATE_ENCODING,
            server_commit=server_commit,
            protocol_version=PROTOCOL_VERSION,
            matchmaking=table.matchmaking,
            cohort_table=table.cohort_table,
            started_at=started_at,
        )
    )
    conn.execute(
        insert(db.seats),
        [
            {"game_id": game, "seat": seat, "player_id": player.id, "memory": "human"}
            for seat, player in enumerate(table.seats)
        ],
    )
    flags = [
        {"game_id": game, "seat": seat, "player_id": player.id} | accepted
        for seat, player in enumerate(table.seats)
        if (accepted := latest_consent(conn, player.id)) is not None
    ]
    if flags:
        conn.execute(insert(db.seat_consents), flags)
    return game


def latest_consent(conn: Connection, player: uuid.UUID) -> dict[str, object] | None:
    """``player``'s latest acceptance, as the columns a seat copies; None if they have none."""
    c = db.consents.c
    row = (
        conn.execute(
            select(
                c.consent_id, c.version, c.us_resident_adult, c.agrees, c.no_outside_communication
            )
            .where(c.player_id == player)
            .order_by(c.at.desc(), c.consent_id.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def load_player(conn: Connection, player: uuid.UUID) -> Player:
    """The player with id ``player``, with their cohort flag (§2.1)."""
    cohort = conn.execute(
        select(db.players.c.cohort).where(db.players.c.player_id == player)
    ).scalar_one()
    return Player(player, cohort)
