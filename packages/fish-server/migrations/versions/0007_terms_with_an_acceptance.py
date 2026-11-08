"""terms with an acceptance

The terms of use and privacy policy are agreed to on the consent screen, with the study
information (T3.8; Terms and Privacy): each acceptance records which version of them was
shown, on ``consents`` and on the ``sign_in_links`` an acceptance travels with. The columns
allow NULL for rows written before there were terms; a person whose latest acceptance has
none accepts again before their next game. Neither column is exported. Drafted by ``alembic
revision --autogenerate``, given the check constraints, which autogenerate does not write.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07 20:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSION = "terms_version IS NULL OR terms_version ~ '^v[0-9]+[.][0-9]+(-pilot)?$'"


def upgrade() -> None:
    for table in ("consents", "sign_in_links"):
        op.add_column(table, sa.Column("terms_version", sa.Text(), nullable=True))
        op.create_check_constraint(op.f(f"ck_{table}_terms_version"), table, VERSION)


def downgrade() -> None:
    for table in ("consents", "sign_in_links"):
        op.drop_column(table, "terms_version")
