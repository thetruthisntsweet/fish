"""consent with a sign-in link

The consent screen comes before the email field (Consent Screen §2): a person who presses
Continue has accepted before they are a player, so the acceptance travels with their sign-in
link, as the version of the text accepted, and becomes a row of ``consents`` when the link is
used (T3.2). The column is on the private ``sign_in_links`` table, never exported. Drafted by
``alembic revision --autogenerate``, given the check constraint, which autogenerate does not
write.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28 17:54:32.978096
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sign_in_links", sa.Column("consent_version", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_sign_in_links_consent_version"),
        "sign_in_links",
        "consent_version IS NULL OR consent_version ~ '^v[0-9]+[.][0-9]+(-pilot)?$'",
    )


def downgrade() -> None:
    op.drop_column("sign_in_links", "consent_version")
