"""Writing a new table to the database (T3.1; docs/corpus.md §2 to §4).

When matchmaking forms a table (``fish_server.lobby``), ``start_game`` writes its ``games``
row (the seed, the versions it is played under, the code that runs it, how it was formed),
one ``seats`` row per seat, and for each person their seat's consent flags, copied from their
latest acceptance (``seat_consents``; Consent Screen §3), before the first action. A person
with no acceptance gets no flags, and the game cannot enter the corpus. All three tables are
append-only: what a game was set up as never changes. Actions and server log rows follow as
the game is played (the game loop); its ending, when the rules end it, or ``abandoned`` when
the server stops it first (``write_ending``, ``abandon_quiet``; docs/corpus.md §3, T3.2).
"""

import secrets
import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import Connection, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as upsert

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


QUIET: Final = timedelta(minutes=5)
"""A game with no ending that has written nothing for this long is no longer being played: a
live game writes a round trip for each connected person every 5 seconds, and its bots act
every few seconds, so even a game of bots is never quiet for a minute."""

_ABANDON_QUIET: Final = """
    INSERT INTO game_endings (game_id, completion)
    SELECT g.game_id, 'abandoned' FROM games g
    WHERE NOT EXISTS (SELECT 1 FROM game_endings e WHERE e.game_id = g.game_id)
      AND NOT (g.game_id = ANY(CAST(:running AS uuid[])))
      AND g.started_at + make_interval(secs => GREATEST(
            COALESCE((SELECT max(a.sent_us) FROM actions a WHERE a.game_id = g.game_id), 0),
            COALESCE((SELECT max(l.at_us) FROM server_log l WHERE l.game_id = g.game_id), 0)
          ) / 1e6) < now() - CAST(:quiet AS interval)
    ON CONFLICT (game_id) DO NOTHING
    RETURNING game_id
"""


def abandon_quiet(
    conn: Connection, *, running: Collection[uuid.UUID], quiet: timedelta = QUIET
) -> list[uuid.UUID]:
    """Mark ``abandoned`` every game with no ending that is not ``running`` here and has
    written nothing for ``quiet`` (docs/corpus.md §3): a game a crash or a restart stopped.
    Returns them. During a deploy the old server's games are still being played, and still
    writing, so they are never caught."""
    found = conn.execute(text(_ABANDON_QUIET), {"running": list(running), "quiet": quiet}).scalars()
    return list(found)


def write_ending(conn: Connection, game: uuid.UUID, completion: str, actions: int) -> str:
    """Write ``game``'s ending, having checked that its stored actions are exactly the
    ``actions`` it played, numbered 0 to ``actions - 1``. If not, its log has a gap, and a
    game whose log cannot replay it is ``abandoned``, whatever the rules said. Writes nothing
    if the game already has an ending. Returns the completion written."""
    count, top = conn.execute(
        select(func.count(), func.max(db.actions.c.seq)).where(db.actions.c.game_id == game)
    ).one()
    if count != actions or (count and top != count - 1):
        completion = "abandoned"
    conn.execute(
        upsert(db.game_endings).values(game_id=game, completion=completion).on_conflict_do_nothing()
    )
    return completion
