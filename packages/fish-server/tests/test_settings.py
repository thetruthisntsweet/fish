"""Tests for fish_server.settings (T2.1 subtasks 9, 13 and 14)."""

import pytest
from sqlalchemy import make_url

from fish_server.settings import (
    ADMIN_DATABASE_URL_VAR,
    APP_PASSWORD_VAR,
    APP_USER_VAR,
    admin_database_url,
    app_login_role,
    app_password,
    database_url,
    normalize_database_url,
)

RENDER_URL = "postgresql://fish:owner-pw@dpg-abc123-a/fish"


def test_admin_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADMIN_DATABASE_URL_VAR, f" {RENDER_URL} \n")
    assert admin_database_url() == "postgresql+psycopg://fish:owner-pw@dpg-abc123-a/fish"


def test_app_url_is_the_admin_url_logged_in_as_fish_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(APP_USER_VAR, raising=False)  # as on Render: the default login
    monkeypatch.setenv(ADMIN_DATABASE_URL_VAR, RENDER_URL)
    monkeypatch.setenv(APP_PASSWORD_VAR, "app/pw+0123456789==")
    url = make_url(database_url())  # characters such as / and = are URL-encoded; parse back
    assert url.drivername == "postgresql+psycopg"
    assert (url.username, url.password) == ("fish_server", "app/pw+0123456789==")
    assert (url.host, url.database) == ("dpg-abc123-a", "fish")


@pytest.mark.parametrize("value", [None, "", "   "])
@pytest.mark.parametrize("var", [ADMIN_DATABASE_URL_VAR, APP_PASSWORD_VAR])
def test_missing_settings_explain_what_to_do(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str | None
) -> None:
    monkeypatch.setenv(ADMIN_DATABASE_URL_VAR, RENDER_URL)
    monkeypatch.setenv(APP_PASSWORD_VAR, "app-pw-0123456789abcdef")
    if value is None:
        monkeypatch.delenv(var)
    else:
        monkeypatch.setenv(var, value)
    with pytest.raises(RuntimeError, match=rf"{var} is not set.*\.env\.example"):
        database_url()


def test_login_name_defaults_to_fish_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(APP_USER_VAR, raising=False)
    assert app_login_role() == "fish_server"


def test_login_name_can_be_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(APP_USER_VAR, "fish_server_test_ab12")
    assert app_login_role() == "fish_server_test_ab12"


@pytest.mark.parametrize("name", ["Fish", "fish-server", "1fish", "fish; DROP ROLE x", "f" * 64])
def test_unsafe_login_names_are_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(APP_USER_VAR, name)
    with pytest.raises(ValueError, match=APP_USER_VAR):
        app_login_role()


def test_the_test_suite_never_uses_the_real_login() -> None:
    """Regression test: the suite once changed fish_server's password on the dev database."""
    assert app_login_role().startswith("fish_server_test_")


def test_app_password_is_read_as_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(APP_PASSWORD_VAR, "app-pw-0123456789abcdef")
    assert app_password() == "app-pw-0123456789abcdef"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("  postgresql://u:p@host/db\n", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_urls_are_normalized_to_psycopg(given: str, expected: str) -> None:
    assert normalize_database_url(given) == expected
