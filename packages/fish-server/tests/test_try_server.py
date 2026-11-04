"""``scripts/try_server.py``'s health checks (T3.6) against the server's real ``/health`` and
``/health/db``: it passes a server whose database is reachable and at the newest migration,
and fails, saying why, one that cannot reach its database or whose deploy has not finished."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from fish_server.app import app
from fish_server.settings import ADMIN_DATABASE_URL_VAR, APP_PASSWORD_VAR

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
