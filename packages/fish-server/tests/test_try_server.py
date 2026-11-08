"""``scripts/try_server.py``'s health checks (T3.6) against the server's real ``/health`` and
``/health/db``: it passes a server whose database is reachable and at the newest migration,
and fails, saying why, one that cannot reach its database or whose deploy has not finished."""

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from fish_server.app import app
from fish_server.settings import (
    ADMIN_DATABASE_URL_VAR,
    APP_PASSWORD_VAR,
    BOT_DELAYS_VAR,
    CONSENT_VERSION_VAR,
)
from fish_server.study import BOT_DELAYS, LAUNCH

SCRIPT = Path(__file__).parents[3] / "scripts" / "try_server.py"


@pytest.fixture
def try_server(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The script, its requests sent to this process's server instead of over the network."""
    spec = importlib.util.spec_from_file_location("try_server", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(app)

    def get(url: str, session: str | None = None) -> tuple[int, dict[str, object]]:
        response = client.get(url.removeprefix("https://site"))
        return response.status_code, json.loads(response.text)

    monkeypatch.setattr(module, "get", get)
    return module


@pytest.mark.usefixtures("server_env")
def test_a_server_at_the_newest_migration_passes(
    try_server: ModuleType, head_revision: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert try_server.newest_migration() == head_revision
    try_server.check_health("https://site")
    assert f"'schema_revision': '{head_revision}'" in capsys.readouterr().out


def test_a_server_that_cannot_reach_its_database_fails(
    try_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(APP_PASSWORD_VAR, "app-pw-0123456789abcdef")
    monkeypatch.delenv(ADMIN_DATABASE_URL_VAR, raising=False)
    with pytest.raises(RuntimeError, match="cannot reach its database"):
        try_server.check_health("https://site")


@pytest.mark.usefixtures("server_env")
def test_a_deploy_that_has_not_finished_fails(
    try_server: ModuleType, monkeypatch: pytest.MonkeyPatch, head_revision: str
) -> None:
    monkeypatch.setattr(try_server, "newest_migration", lambda: "0099_newer")
    with pytest.raises(RuntimeError, match=f"at {head_revision}, .* newest migration is 0099"):
        try_server.check_health("https://site")


@pytest.mark.usefixtures("server_env")
def test_the_bots_wait_as_the_checkout_says_the_site_s_bots_should(
    try_server: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = date(2026, 12, 1)
    try_server.check_bot_delays("https://site", before)  # the study's: its table
    assert f"bots:   {BOT_DELAYS}" in capsys.readouterr().out
    monkeypatch.setenv(CONSENT_VERSION_VAR, "v1.0-pilot")
    try_server.check_bot_delays("https://site", before)  # the pilot's: uniform
    assert "bots:   uniform-1.5-4s-v1" in capsys.readouterr().out
    monkeypatch.setenv(BOT_DELAYS_VAR, BOT_DELAYS)
    with pytest.raises(RuntimeError, match=f"wait by {BOT_DELAYS}, but on the pilot site"):
        try_server.check_bot_delays("https://site", before)


@pytest.mark.usefixtures("server_env")
def test_a_stand_in_fails_on_the_study_s_site_from_the_day_it_opens(
    try_server: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(try_server, "BOT_DELAYS", "stand-in-v1")
    monkeypatch.setenv(BOT_DELAYS_VAR, "stand-in-v1")
    try_server.check_bot_delays("https://site", LAUNCH - timedelta(days=1))
    with pytest.raises(RuntimeError, match="stand-in-v1 is a stand-in"):
        try_server.check_bot_delays("https://site", LAUNCH)
