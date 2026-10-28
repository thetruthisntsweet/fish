"""Database metadata shared by the server and Alembic (T2.1 subtask 9; tables from T1.6 and
T3.1).

The tables hold what docs/corpus.md §2 to §5 says every website game records. Migration 0003
creates them; ``tests/test_corpus_tables.py`` checks that this metadata and the migrated
database agree, so the two cannot drift.

Every table that records play or consent is in ``APPEND_ONLY``: its triggers refuse UPDATE,
DELETE and TRUNCATE for every role, the owner included (``privileges.append_only_sql``), and
the server's login may only read and insert anyway (D15). A game's end is therefore a row of
its own in ``game_endings``, not a column filled in later. Only the tables in ``PRIVATE`` are
outside the list: ``player_contacts``, which holds email addresses, and the sign-in links and
sessions (T3.1). They never leave the server (§7), and an address can be removed on request.

Constraints repeat the rules of the record format (``fish_rules.corpus``) where a column
alone can enforce them; whatever needs a replay is checked when a record is read. Nothing is
stored twice: who answered a note question is whoever holds that seat.
"""

from datetime import datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    Sequence,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
"""Every index and constraint gets a predictable name, so later migrations can drop or
change it by name instead of guessing what PostgreSQL called it."""

metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _timestamp(name: str) -> Column[datetime]:
    """A wall-clock time the database fills in when the row is written."""
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


signup_numbers = Sequence("signup_numbers", start=0, minvalue=0, metadata=metadata)
"""Sign-up numbers, 0, 1, 2, ... The server draws one with ``nextval`` and computes the
cohort from it (``fish_rules.cohort.in_cohort``) before inserting the player. A number drawn
for a sign-up that then fails is never reused, so the cohort is exactly 3 in every block of
20 numbers rather than of 20 players."""

# ---------------------------------------------------------------- players (§2)

players = Table(
    "players",
    metadata,
    Column("player_id", UUID(as_uuid=True), primary_key=True),
    Column("signup_number", BigInteger, nullable=False, unique=True),
    Column("cohort", Boolean, nullable=False),
    _timestamp("signed_up_at"),
    CheckConstraint("signup_number >= 0", name="signup_number"),
)

player_contacts = Table(
    "player_contacts",
    metadata,
    Column("player_id", ForeignKey("players.player_id"), primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    _timestamp("added_at"),
)

consent_events = Table(
    "consent_events",
    metadata,
    Column("event_id", BigInteger, primary_key=True, autoincrement=True),
    Column("player_id", ForeignKey("players.player_id"), nullable=False, index=True),
    _timestamp("at"),
    Column("consent_version", Text, nullable=False),
    Column("research_use", Boolean, nullable=False),
    Column("public_release", Boolean, nullable=False),
    Column("no_outside_communication", Boolean, nullable=False),
    Column("no_notes", Boolean, nullable=False),
)

age_events = Table(
    "age_events",
    metadata,
    Column("event_id", BigInteger, primary_key=True, autoincrement=True),
    Column("player_id", ForeignKey("players.player_id"), nullable=False, index=True),
    _timestamp("at"),
    Column("confirmed_18_plus", Boolean, nullable=False),
)

# ---------------------------------------------------------------- sign-in (T3.1)
#
# Links and sessions are kept as tokens' SHA-256 hashes, never the tokens. The server's login
# may only insert, so using a link and ending a session are rows of their own; a primary key
# makes each happen at most once. None of these is exported, and an address removed on
# request is removed from ``sign_in_links`` too, so they are not append-only.


def _token_hash(name: str) -> Column[str]:
    return Column(name, Text, primary_key=True)


sign_in_links = Table(
    "sign_in_links",
    metadata,
    _token_hash("token_hash"),
    Column("email", Text, nullable=False),
    _timestamp("created_at"),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index(None, "email", "created_at"),
    Index(None, "created_at"),
    CheckConstraint("length(token_hash) = 64", name="token_hash"),
)

sign_in_uses = Table(
    "sign_in_uses",
    metadata,
    Column("token_hash", ForeignKey("sign_in_links.token_hash"), primary_key=True),
    _timestamp("used_at"),
)

sessions = Table(
    "sessions",
    metadata,
    _token_hash("token_hash"),
    Column("player_id", ForeignKey("players.player_id"), nullable=False, index=True),
    _timestamp("created_at"),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("length(token_hash) = 64", name="token_hash"),
)

session_ends = Table(
    "session_ends",
    metadata,
    Column("token_hash", ForeignKey("sessions.token_hash"), primary_key=True),
    _timestamp("ended_at"),
)

PRIVATE: Final[tuple[str, ...]] = (
    "player_contacts",
    "sign_in_links",
    "sign_in_uses",
    "sessions",
    "session_ends",
)
"""Tables that never leave the server (docs/corpus.md §7) and whose rows an administrator may
remove: contact addresses, sign-in links and sessions. Every other table is append-only."""

# ---------------------------------------------------------------- games (§3)

games = Table(
    "games",
    metadata,
    Column("game_id", UUID(as_uuid=True), primary_key=True),
    Column("seed", Numeric(20, 0), nullable=False),
    Column("ruleset", Text, nullable=False),
    Column("action_encoding", Text, nullable=False),
    Column("state_encoding", Text, nullable=False),
    Column("server_commit", Text, nullable=False),
    Column("protocol_version", Integer, nullable=False),
    Column("matchmaking", Text, nullable=False),
    Column("cohort_table", Boolean, nullable=False),
    _timestamp("created_at"),
    Column("started_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("seed >= 0 AND seed < 18446744073709551616", name="seed"),
    CheckConstraint("matchmaking IN ('solo', 'group')", name="matchmaking"),
    CheckConstraint("protocol_version >= 1", name="protocol_version"),
)

game_endings = Table(
    "game_endings",
    metadata,
    Column("game_id", ForeignKey("games.game_id"), primary_key=True),
    Column("completion", Text, nullable=False),
    _timestamp("ended_at"),
    CheckConstraint("completion IN ('finished', 'unfinished', 'abandoned')", name="completion"),
)

# ---------------------------------------------------------------- seats (§4)

seats = Table(
    "seats",
    metadata,
    Column("game_id", ForeignKey("games.game_id"), primary_key=True),
    Column("seat", SmallInteger, primary_key=True),
    Column("player_id", ForeignKey("players.player_id"), nullable=True),
    Column("agent", Text, nullable=True),
    Column("memory", Text, nullable=False),
    Column("k", Integer, nullable=True),
    UniqueConstraint("game_id", "player_id"),
    CheckConstraint("seat BETWEEN 0 AND 5", name="seat"),
    CheckConstraint(
        "(player_id IS NOT NULL AND agent IS NULL AND memory = 'human' AND k IS NULL)"
        " OR (player_id IS NULL AND agent IS NOT NULL"
        " AND memory IN ('full', 'last-k', 'none')"
        " AND (memory = 'last-k') = (k IS NOT NULL) AND (k IS NULL OR k >= 1))",
        name="controller",
    ),
)

note_answers = Table(
    "note_answers",
    metadata,
    Column("game_id", UUID(as_uuid=True), primary_key=True),
    Column("seat", SmallInteger, primary_key=True),
    Column("question_version", Text, nullable=False),
    Column("answer", Text, nullable=False),
    _timestamp("at"),
    ForeignKeyConstraint(["game_id", "seat"], ["seats.game_id", "seats.seat"]),
    CheckConstraint("answer IN ('yes', 'no', 'declined')", name="answer"),
)

# ---------------------------------------------------------------- the log (§5)

actions = Table(
    "actions",
    metadata,
    Column("game_id", ForeignKey("games.game_id"), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("action", JSONB, nullable=False),
    Column("cause_seat", SmallInteger, nullable=True),
    Column("cause_timer", Text, nullable=True),
    Column("received_us", BigInteger, nullable=False),
    Column("sent_us", BigInteger, nullable=False),
    CheckConstraint("seq >= 0", name="seq"),
    CheckConstraint(
        "(cause_seat IS NULL) <> (cause_timer IS NULL)"
        " AND (cause_seat IS NULL OR cause_seat BETWEEN 0 AND 5)"
        " AND (cause_timer IS NULL OR cause_timer IN ('window', 'assignment', 'choice'))",
        name="cause",
    ),
    CheckConstraint("received_us >= 0 AND sent_us >= received_us", name="times"),
)

server_log = Table(
    "server_log",
    metadata,
    Column("row_id", BigInteger, primary_key=True, autoincrement=True),
    Column("game_id", ForeignKey("games.game_id"), nullable=False),
    Column("after_seq", Integer, nullable=False),
    Column("at_us", BigInteger, nullable=False),
    Column("seat", SmallInteger, nullable=False),
    Column("type", Text, nullable=False),
    Column("data", JSONB, nullable=False),
    Index(None, "game_id", "row_id"),
    CheckConstraint("after_seq >= 0 AND at_us >= 0", name="position"),
    CheckConstraint("seat BETWEEN 0 AND 5", name="seat"),
    CheckConstraint(
        "type IN ('rtt', 'rejected', 'bot_delay', 'connection', 'handover')", name="type"
    ),
)

APPEND_ONLY: Final[tuple[str, ...]] = (
    "players",
    "consent_events",
    "age_events",
    "games",
    "game_endings",
    "seats",
    "note_answers",
    "actions",
    "server_log",
)
"""Tables whose rows are never changed or removed once written (docs/corpus.md §1)."""
