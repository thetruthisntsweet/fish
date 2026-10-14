"""app role and append-only trigger function

Least privilege for the running server (T2.1 subtask 14, §11). Creates the ``fish_app``
role, which may read and insert on every table later migrations create but never update,
delete, truncate or create tables, and the trigger function that later makes the event log
append-only (``fish_server.privileges.append_only_sql``). The ``fish_server`` login itself
is created by ``python -m fish_server.deploy``, because it needs a password.

Roles belong to the whole database server, not to one database, so downgrade removes this
database's grants but leaves the role in place for any other database that uses it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 01:38:38.064220
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fish_app') THEN
                CREATE ROLE fish_app NOLOGIN;
            END IF;
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO fish_app', current_database());
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO fish_app")
    # Every table and sequence that migrations create from now on: read and insert only.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT ON TABLES TO fish_app"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO fish_app")
    # The one table that already exists: /health/db reads it.
    op.execute("GRANT SELECT ON alembic_version TO fish_app")
    op.execute(
        """
        CREATE FUNCTION fish_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION fish_forbid_change()")
    op.execute("REVOKE SELECT ON alembic_version FROM fish_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE ON SEQUENCES FROM fish_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT ON TABLES FROM fish_app"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM fish_app")
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM fish_app', current_database());
        END
        $$
        """
    )
