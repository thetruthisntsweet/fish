"""baseline

The empty starting point every later migration builds on (T2.1 subtask 9). Creates
nothing except Alembic's own ``alembic_version`` table, which records which migrations a
database has had. The first real tables arrive with T1.6 and T3.2.

Revision ID: 0001
Revises: (none)
Create Date: <leave whatever date Alembic wrote>
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
