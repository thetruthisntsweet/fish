"""sign-in links and sessions

The tables of email sign-in (T3.1): links and their uses, sessions and their ends, each kept
as the SHA-256 hash of its token. The server's login may only read and insert (migration
0002), so using a link and ending a session are rows of their own. These tables never leave
the server and are not append-only (``fish_server.db.PRIVATE``), so an administrator can remove
an address on request and prune expired rows. Drafted by ``alembic revision --autogenerate``
from ``fish_server.db``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 22:34:32.211107
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sign_in_links",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(token_hash) = 64", name=op.f("ck_sign_in_links_token_hash")),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sign_in_links")),
    )
    op.create_index(
        op.f("ix_sign_in_links_created_at"), "sign_in_links", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_sign_in_links_email_created_at"),
        "sign_in_links",
        ["email", "created_at"],
        unique=False,
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(token_hash) = 64", name=op.f("ck_sessions_token_hash")),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.player_id"], name=op.f("fk_sessions_player_id_players")
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
    )
    op.create_index(op.f("ix_sessions_player_id"), "sessions", ["player_id"], unique=False)
    op.create_table(
        "sign_in_uses",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "used_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["token_hash"],
            ["sign_in_links.token_hash"],
            name=op.f("fk_sign_in_uses_token_hash_sign_in_links"),
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sign_in_uses")),
    )
    op.create_table(
        "session_ends",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "ended_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["token_hash"],
            ["sessions.token_hash"],
            name=op.f("fk_session_ends_token_hash_sessions"),
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_session_ends")),
    )


def downgrade() -> None:
    op.drop_table("session_ends")
    op.drop_table("sign_in_uses")
    op.drop_index(op.f("ix_sessions_player_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_sign_in_links_email_created_at"), table_name="sign_in_links")
    op.drop_index(op.f("ix_sign_in_links_created_at"), table_name="sign_in_links")
    op.drop_table("sign_in_links")
