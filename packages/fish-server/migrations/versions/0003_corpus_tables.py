"""corpus tables

The tables of docs/corpus.md §2 to §5 (T1.6): players and their contact addresses, consent
and age events, games and their endings, seats, note answers, the action log and the server
log, plus the ``signup_numbers`` sequence. Every table except ``player_contacts`` is made
append-only (``fish_server.db.APPEND_ONLY``, ``privileges.append_only_sql``); migration 0002's
default privileges already let ``fish_app`` read and insert on all of them and nothing else.
Drafted by ``alembic revision --autogenerate`` from ``fish_server.db``, then given the
sequence and the triggers, which autogenerate does not write.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 11:36:51.368977
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from fish_server.privileges import append_only_sql

APPEND_ONLY = (
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
"""Written out here rather than imported, so this migration does not change if the list in
``fish_server.db`` does."""

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE signup_numbers MINVALUE 0 START WITH 0")
    op.create_table(
        "games",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("seed", sa.Numeric(precision=20, scale=0), nullable=False),
        sa.Column("ruleset", sa.Text(), nullable=False),
        sa.Column("action_encoding", sa.Text(), nullable=False),
        sa.Column("state_encoding", sa.Text(), nullable=False),
        sa.Column("server_commit", sa.Text(), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("matchmaking", sa.Text(), nullable=False),
        sa.Column("cohort_table", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("matchmaking IN ('solo', 'group')", name=op.f("ck_games_matchmaking")),
        sa.CheckConstraint("protocol_version >= 1", name=op.f("ck_games_protocol_version")),
        sa.CheckConstraint("seed >= 0 AND seed < 18446744073709551616", name=op.f("ck_games_seed")),
        sa.PrimaryKeyConstraint("game_id", name=op.f("pk_games")),
    )
    op.create_table(
        "players",
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column("signup_number", sa.BigInteger(), nullable=False),
        sa.Column("cohort", sa.Boolean(), nullable=False),
        sa.Column(
            "signed_up_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("signup_number >= 0", name=op.f("ck_players_signup_number")),
        sa.PrimaryKeyConstraint("player_id", name=op.f("pk_players")),
        sa.UniqueConstraint("signup_number", name=op.f("uq_players_signup_number")),
    )
    op.create_table(
        "actions",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("action", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cause_seat", sa.SmallInteger(), nullable=True),
        sa.Column("cause_timer", sa.Text(), nullable=True),
        sa.Column("received_us", sa.BigInteger(), nullable=False),
        sa.Column("sent_us", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "(cause_seat IS NULL) <> (cause_timer IS NULL)"
            " AND (cause_seat IS NULL OR cause_seat BETWEEN 0 AND 5)"
            " AND (cause_timer IS NULL OR cause_timer IN ('window', 'assignment', 'choice'))",
            name=op.f("ck_actions_cause"),
        ),
        sa.CheckConstraint(
            "received_us >= 0 AND sent_us >= received_us", name=op.f("ck_actions_times")
        ),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_actions_seq")),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.game_id"], name=op.f("fk_actions_game_id_games")
        ),
        sa.PrimaryKeyConstraint("game_id", "seq", name=op.f("pk_actions")),
    )
    op.create_table(
        "age_events",
        sa.Column("event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("confirmed_18_plus", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_age_events_player_id_players")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_age_events")),
    )
    op.create_index(op.f("ix_age_events_player_id"), "age_events", ["player_id"], unique=False)
    op.create_table(
        "consent_events",
        sa.Column("event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("consent_version", sa.Text(), nullable=False),
        sa.Column("research_use", sa.Boolean(), nullable=False),
        sa.Column("public_release", sa.Boolean(), nullable=False),
        sa.Column("no_outside_communication", sa.Boolean(), nullable=False),
        sa.Column("no_notes", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_consent_events_player_id_players")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_consent_events")),
    )
    op.create_index(
        op.f("ix_consent_events_player_id"), "consent_events", ["player_id"], unique=False
    )
    op.create_table(
        "game_endings",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("completion", sa.Text(), nullable=False),
        sa.Column(
            "ended_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "completion IN ('finished', 'unfinished', 'abandoned')",
            name=op.f("ck_game_endings_completion"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.game_id"], name=op.f("fk_game_endings_game_id_games")
        ),
        sa.PrimaryKeyConstraint("game_id", name=op.f("pk_game_endings")),
    )
    op.create_table(
        "player_contacts",
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_player_contacts_player_id_players")
        ),
        sa.PrimaryKeyConstraint("player_id", name=op.f("pk_player_contacts")),
        sa.UniqueConstraint("email", name=op.f("uq_player_contacts_email")),
    )
    op.create_table(
        "seats",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=True),
        sa.Column("agent", sa.Text(), nullable=True),
        sa.Column("memory", sa.Text(), nullable=False),
        sa.Column("k", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(player_id IS NOT NULL AND agent IS NULL AND memory = 'human' AND k IS NULL)"
            " OR (player_id IS NULL AND agent IS NOT NULL"
            " AND memory IN ('full', 'last-k', 'none')"
            " AND (memory = 'last-k') = (k IS NOT NULL) AND (k IS NULL OR k >= 1))",
            name=op.f("ck_seats_controller"),
        ),
        sa.CheckConstraint("seat BETWEEN 0 AND 5", name=op.f("ck_seats_seat")),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.game_id"], name=op.f("fk_seats_game_id_games")
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_seats_player_id_players")
        ),
        sa.PrimaryKeyConstraint("game_id", "seat", name=op.f("pk_seats")),
        sa.UniqueConstraint("game_id", "player_id", name=op.f("uq_seats_game_id_player_id")),
    )
    op.create_table(
        "server_log",
        sa.Column("row_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("after_seq", sa.Integer(), nullable=False),
        sa.Column("at_us", sa.BigInteger(), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "type IN ('rtt', 'rejected', 'bot_delay', 'connection', 'handover')",
            name=op.f("ck_server_log_type"),
        ),
        sa.CheckConstraint("after_seq >= 0 AND at_us >= 0", name=op.f("ck_server_log_position")),
        sa.CheckConstraint("seat BETWEEN 0 AND 5", name=op.f("ck_server_log_seat")),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.game_id"], name=op.f("fk_server_log_game_id_games")
        ),
        sa.PrimaryKeyConstraint("row_id", name=op.f("pk_server_log")),
    )
    op.create_index(
        op.f("ix_server_log_game_id_row_id"), "server_log", ["game_id", "row_id"], unique=False
    )
    op.create_table(
        "note_answers",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("question_version", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "answer IN ('yes', 'no', 'declined')", name=op.f("ck_note_answers_answer")
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "seat"],
            ["seats.game_id", "seats.seat"],
            name=op.f("fk_note_answers_game_id_seat_seats"),
        ),
        sa.PrimaryKeyConstraint("game_id", "seat", name=op.f("pk_note_answers")),
    )
    for table in APPEND_ONLY:
        for statement in append_only_sql(table):
            op.execute(statement)


def downgrade() -> None:
    op.drop_table("note_answers")
    op.drop_index(op.f("ix_server_log_game_id_row_id"), table_name="server_log")
    op.drop_table("server_log")
    op.drop_table("seats")
    op.drop_table("player_contacts")
    op.drop_table("game_endings")
    op.drop_index(op.f("ix_consent_events_player_id"), table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_index(op.f("ix_age_events_player_id"), table_name="age_events")
    op.drop_table("age_events")
    op.drop_table("actions")
    op.drop_table("players")
    op.drop_table("games")
    op.execute("DROP SEQUENCE signup_numbers")
