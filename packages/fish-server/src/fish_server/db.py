"""Database metadata shared by the server and Alembic (T2.1 subtask 9).

Tables are added here from T1.6 and T3.2 onward. Alembic compares this metadata with the
database to draft new migrations.
"""

from sqlalchemy import MetaData

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
