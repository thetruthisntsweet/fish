"""Shared fixtures for fish-server tests.

Database tests need FISH_TEST_DATABASE_URL (see .env.example). Each gets its own throwaway
database, created before the test and dropped after it, so development data is never
touched. Without the variable, those tests are skipped with a visible reason.

Logins belong to the whole database server, not to one database, so the suite also uses its
own login (``fish_server_test_<random>``) instead of ``fish_server``: running the tests must
never change the password of the login your development server uses.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, make_url, pool, text

from fish_server.database import dispose_engine
from fish_server.privileges import sync_login_role
from fish_server.settings import ADMIN_DATABASE_URL_VAR, APP_PASSWORD_VAR, APP_USER_VAR

ADMIN_URL = os.environ.get("FISH_TEST_DATABASE_URL", "").strip()
REPO = Path(__file__).resolve().parents[3]
TEST_APP_PASSWORD = "test-app-password-0123456789"

TEST_LOGIN_ROLE = f"fish_server_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session", autouse=True)
def _own_login_for_the_test_suite() -> Iterator[None]:
    """Point every test at the suite's own login; remove that login when the run ends."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(APP_USER_VAR, TEST_LOGIN_ROLE)
        yield
    if ADMIN_URL:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
        with admin.connect() as conn:
            conn.execute(text(f"DROP ROLE IF EXISTS {TEST_LOGIN_ROLE}"))
        admin.dispose()


@pytest.fixture
def fresh_database_url() -> Iterator[str]:
    """URL of a new, empty database; dropped afterwards even if the test fails."""
    if not ADMIN_URL:
        pytest.skip("FISH_TEST_DATABASE_URL not set: start infra/docker-compose.yml, create .env")
    name = f"fish_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        dispose_engine()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def migrated_database_url(fresh_database_url: str) -> str:
    """Like fresh_database_url, but already migrated to the latest revision."""
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", fresh_database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    return fresh_database_url


@pytest.fixture(scope="session")
def head_revision() -> str:
    """The latest migration, which a migrated database is at."""
    head = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini"))).get_current_head()
    assert head is not None
    return head


@pytest.fixture
def server_env(migrated_database_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A migrated database with the fish_server login set up, and the environment pointing
    at it exactly as on Render. Returns the admin (owner) URL."""
    engine = create_engine(migrated_database_url, poolclass=pool.NullPool)
    sync_login_role(engine, TEST_APP_PASSWORD)
    engine.dispose()
    monkeypatch.setenv(ADMIN_DATABASE_URL_VAR, migrated_database_url)
    monkeypatch.setenv(APP_PASSWORD_VAR, TEST_APP_PASSWORD)
    return migrated_database_url


@pytest.fixture(autouse=True)
def _fresh_engine_per_test() -> Iterator[None]:
    """get_engine() caches one engine per process; give every test its own, and close it."""
    dispose_engine()
    yield
    dispose_engine()
