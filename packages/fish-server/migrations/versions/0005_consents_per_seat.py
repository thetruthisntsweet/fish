"""consents per seat

Consent as the approved Consent Screen (§3) and Research Plan (§6) describe it, replacing
migration 0003's ``consent_events`` and ``age_events`` (T3.2): ``consents``, one row per
acceptance with the text's version and the screen's three confirmations (US-resident legal
adult, agrees to take part, no outside communication); ``withdrawals``, a record of its own
with how it came (website or email); and ``seat_consents``, each person's seat's flags, copied
from their latest acceptance when the game starts. All three are append-only. No study data
existed when this was written: the dropped tables held only test rows on staging.

``seats`` gains a unique key on (game, seat, player) so a seat's flags can be tied to the seat
and to its own player's acceptance by foreign keys. Drafted by ``alembic revision
--autogenerate`` from ``fish_server.db``, then reordered so that key exists before it is
referred to, and given the triggers, which autogenerate does not write.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 17:28:39.258838
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from fish_server.privileges import append_only_sql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPEND_ONLY = ("consents", "withdrawals", "seat_consents")
"""Written out here rather than imported, so this migration does not change if the list in
``fish_server.db`` does."""


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_seats_game_id_seat_player_id"), "seats", ["game_id", "seat", "player_id"]
    )
    op.create_table(
        "consents",
        sa.Column("consent_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("us_resident_adult", sa.Boolean(), nullable=False),
        sa.Column("agrees", sa.Boolean(), nullable=False),
        sa.Column("no_outside_communication", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "version ~ '^v[0-9]+[.][0-9]+(-pilot)?$'", name=op.f("ck_consents_version")
        ),
        sa.CheckConstraint(
            "us_resident_adult AND agrees AND no_outside_communication",
            name=op.f("ck_consents_confirmed"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_consents_player_id_players")
        ),
        sa.PrimaryKeyConstraint("consent_id", name=op.f("pk_consents")),
        sa.UniqueConstraint(
            "consent_id",
            "player_id",
            "version",
            name=op.f("uq_consents_consent_id_player_id_version"),
        ),
    )
    op.create_index(op.f("ix_consents_player_id"), "consents", ["player_id"], unique=False)
    op.create_table(
        "withdrawals",
        sa.Column("withdrawal_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.CheckConstraint("channel IN ('website', 'email')", name=op.f("ck_withdrawals_channel")),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_withdrawals_player_id_players")
        ),
        sa.PrimaryKeyConstraint("withdrawal_id", name=op.f("pk_withdrawals")),
    )
    op.create_index(op.f("ix_withdrawals_player_id"), "withdrawals", ["player_id"], unique=False)
    op.create_table(
        "seat_consents",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column("consent_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("us_resident_adult", sa.Boolean(), nullable=False),
        sa.Column("agrees", sa.Boolean(), nullable=False),
        sa.Column("no_outside_communication", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "us_resident_adult AND agrees AND no_outside_communication",
            name=op.f("ck_seat_consents_confirmed"),
        ),
        sa.ForeignKeyConstraint(
            ["consent_id", "player_id", "version"],
            ["consents.consent_id", "consents.player_id", "consents.version"],
            name=op.f("fk_seat_consents_consent_id_player_id_version_consents"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id", "seat", "player_id"],
            ["seats.game_id", "seats.seat", "seats.player_id"],
            name=op.f("fk_seat_consents_game_id_seat_player_id_seats"),
        ),
        sa.PrimaryKeyConstraint("game_id", "seat", name=op.f("pk_seat_consents")),
    )
    op.drop_index(op.f("ix_age_events_player_id"), table_name="age_events")
    op.drop_table("age_events")
    op.drop_index(op.f("ix_consent_events_player_id"), table_name="consent_events")
    op.drop_table("consent_events")
    for table in APPEND_ONLY:
        for statement in append_only_sql(table):
            op.execute(statement)


def downgrade() -> None:
    op.create_table(
        "consent_events",
        sa.Column("event_id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("consent_version", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("research_use", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("public_release", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("no_outside_communication", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("no_notes", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_consent_events_player_id_players")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_consent_events")),
    )
    op.create_index(
        op.f("ix_consent_events_player_id"), "consent_events", ["player_id"], unique=False
    )
    op.create_table(
        "age_events",
        sa.Column("event_id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("confirmed_18_plus", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_age_events_player_id_players")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_age_events")),
    )
    op.create_index(op.f("ix_age_events_player_id"), "age_events", ["player_id"], unique=False)
    for table in ("consent_events", "age_events"):
        for statement in append_only_sql(table):
            op.execute(statement)
    op.drop_table("seat_consents")
    op.drop_index(op.f("ix_withdrawals_player_id"), table_name="withdrawals")
    op.drop_table("withdrawals")
    op.drop_index(op.f("ix_consents_player_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_constraint(op.f("uq_seats_game_id_seat_player_id"), "seats", type_="unique")
