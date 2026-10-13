"""Tests for fish_server.protocol (T2.1 subtask 8)."""

import pytest
from pydantic import ValidationError

from fish_rules.rng import RNG_ALGORITHM
from fish_rules.version import RULESET_VERSION
from fish_server.protocol import (
    CLIENT_MESSAGES,
    PROTOCOL_VERSION,
    SERVER_MESSAGES,
    ClientHello,
    ServerHello,
    server_hello,
)


def test_server_hello_reports_the_versions_this_server_runs() -> None:
    hello = server_hello()
    assert hello.type == "server_hello"
    assert hello.protocol_version == PROTOCOL_VERSION
    assert hello.ruleset_version == RULESET_VERSION
    assert hello.rng_algorithm == RNG_ALGORITHM


def test_server_hello_round_trips_through_json() -> None:
    hello = server_hello()
    assert ServerHello.model_validate_json(hello.model_dump_json()) == hello


def test_client_hello_parses_from_json() -> None:
    raw = '{"type": "client_hello", "protocol_version": 1}'
    assert ClientHello.model_validate_json(raw) == ClientHello(
        type="client_hello", protocol_version=1
    )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ClientHello.model_validate({"type": "client_hello", "protocol_version": 1, "x": 0})


def test_wrong_type_tag_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClientHello.model_validate({"type": "server_hello", "protocol_version": 1})


def test_protocol_version_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ClientHello.model_validate({"type": "client_hello", "protocol_version": 0})


def test_messages_are_immutable() -> None:
    hello = server_hello()
    with pytest.raises(ValidationError, match="frozen"):
        hello.ruleset_version = "2.0"  # pyright: ignore[reportAttributeAccessIssue]


def test_every_message_has_a_unique_type_tag() -> None:
    tags = [m.model_fields["type"].annotation for m in (*CLIENT_MESSAGES, *SERVER_MESSAGES)]
    assert len(tags) == len(set(tags))
