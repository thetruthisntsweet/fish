"""Tests for fish_server.app (T2.1 subtask 12)."""

import pytest
from fastapi.testclient import TestClient

from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION
from fish_server.app import app
from fish_server.protocol import PROTOCOL_VERSION, ServerHello


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
