"""game exclusions

A game can be left out of the corpus by a recorded decision after a fault (T4.4;
``fish_server.exclude``, docs/runbooks/collection.md): ``game_exclusions`` holds the game, why,
and when. It is append-only like every corpus table, so an exclusion is never changed or
removed, and the game itself is never touched.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-10 04:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from fish_server.privileges import append_only_sql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_exclusions",
        sa.Column("game_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("length(btrim(reason)) >= 10", name=op.f("ck_game_exclusions_reason")),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.game_id"], name=op.f("fk_game_exclusions_game_id_games")
        ),
        sa.PrimaryKeyConstraint("game_id", name=op.f("pk_game_exclusions")),
    )
    for statement in append_only_sql("game_exclusions"):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("game_exclusions")
