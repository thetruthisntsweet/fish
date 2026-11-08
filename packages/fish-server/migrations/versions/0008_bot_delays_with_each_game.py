"""bot delays with each game

Each game records the version of the bots' delay table it was played with (R.8.8; T4.2;
``fish_agents.delays``), so its bot waits follow from its seed and that version. Games
written before this were all played with ``uniform-1.5-4s-v1``, so the column is filled with
it, and then has no default: the server writes it for every new game.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = "uniform-1.5-4s-v1"
NAME = "bot_delays ~ '^[a-z0-9][a-z0-9.-]*$'"


def upgrade() -> None:
    op.add_column(
        "games", sa.Column("bot_delays", sa.Text(), nullable=False, server_default=BEFORE)
    )
    op.alter_column("games", "bot_delays", server_default=None)
    op.create_check_constraint(op.f("ck_games_bot_delays"), "games", NAME)


def downgrade() -> None:
    op.drop_column("games", "bot_delays")
