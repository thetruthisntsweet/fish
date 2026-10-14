"""Tests for fish_server.app (T2.1 subtask 12)."""

import pytest
from fastapi.testclient import TestClient

from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION
from fish_server.app import app
from fish_server.database import get_engine
from fish_server.protocol import PROTOCOL_VERSION, ServerHello
from fish_server.settings import DATABASE_URL_VAR


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_reports_ok_and_versions(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "server_version": "0.0.0",
        "ruleset_version": RULESET_VERSION,
        "rng_algorithm": RNG_ALGORITHM,
        "protocol_version": PROTOCOL_VERSION,
    }


def test_interactive_docs_are_not_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404


def test_echo_sends_server_hello_first(client: TestClient) -> None:
    with client.websocket_connect("/ws/echo") as ws:
        hello = ServerHello.model_validate_json(ws.receive_text())
    assert hello.ruleset_version == RULESET_VERSION


def test_echo_returns_every_message_in_order(client: TestClient) -> None:
    with client.websocket_connect("/ws/echo") as ws:
        ws.receive_text()  # ServerHello
        for message in ["one", "two", "", "ünïcødé ♠"]:
            ws.send_text(message)
            assert ws.receive_text() == message


def test_health_db_reports_the_migrated_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, migrated_database_url)
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"database": "ok", "schema_revision": "0001"}


@pytest.mark.parametrize("url", [None, "postgresql://u:p@127.0.0.1:1/nothing_listens_here"])
def test_health_db_is_503_without_a_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, url: str | None
) -> None:
    if url is None:
        monkeypatch.delenv(DATABASE_URL_VAR, raising=False)
    else:
        monkeypatch.setenv(DATABASE_URL_VAR, url)
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"database": "unavailable", "schema_revision": None}
    assert "127.0.0.1" not in response.text  # no connection details leak out


def test_health_does_not_need_a_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DATABASE_URL_VAR, raising=False)
    assert client.get("/health").status_code == 200


def test_server_shutdown_closes_database_connections(
    monkeypatch: pytest.MonkeyPatch, migrated_database_url: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_VAR, migrated_database_url)
    with TestClient(app) as running:  # "with" runs the startup and shutdown hooks
        assert running.get("/health/db").status_code == 200
        assert get_engine.cache_info().currsize == 1
    assert get_engine.cache_info().currsize == 0
