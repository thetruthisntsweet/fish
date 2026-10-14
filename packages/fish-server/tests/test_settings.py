"""Tests for fish_server.settings (T2.1 subtask 9)."""

import pytest

from fish_server.settings import DATABASE_URL_VAR, database_url, normalize_database_url


def test_database_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, " postgresql+psycopg://u:p@localhost:5432/db \n")
    assert database_url() == "postgresql+psycopg://u:p@localhost:5432/db"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_database_url_explains_what_to_do(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(DATABASE_URL_VAR, raising=False)
    else:
        monkeypatch.setenv(DATABASE_URL_VAR, value)
    with pytest.raises(RuntimeError, match=r"\.env\.example"):
        database_url()


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


def test_database_url_normalizes_what_render_provides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, "postgresql://fish:pw@dpg-abc123-a/fish")
    assert database_url() == "postgresql+psycopg://fish:pw@dpg-abc123-a/fish"
