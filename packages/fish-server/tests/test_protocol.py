"""Tests for fish_server.protocol (T2.1 subtask 8; the game's messages, T3.1).

Client messages are read strictly and exactly. The ``View`` model mirrors ``fish-view-v1``:
every frozen view vector, and every seat's view at every step of random website games, reads
as a ``View`` and writes back to exactly the same data. Every update tells the seat exactly
what the table lets it do and which timers run."""

import json
from pathlib import Path
from typing import Any, Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from fish_agents.memory import NONE
from fish_rules.action_index import decode, encode
from fish_rules.cards import SEATS
from fish_rules.rng import RNG_ALGORITHM, SplitMix64
from fish_rules.state import Phase
from fish_rules.version import RULESET_VERSION
from fish_rules.view import view_to_data
from fish_server.protocol import (
    CLIENT_MESSAGES,
    PROTOCOL_VERSION,
    ROOM_CODE_ALPHABET,
    SERVER_MESSAGES,
    Act,
    ClientHello,
    JoinRoom,
    Lobby,
    NoteAnswer,
    Press,
    ServerHello,
    Update,
    View,
    note_question,
    parse_client_message,
    server_hello,
    update,
)
from fish_server.table import SECOND_US, TURN_US, WINDOW_US, Controller, Table

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 160)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games, every seat's update checked at every step: a hundred-and-sixtieth of the
profile's examples (10 in dev and CI, 312 nightly)."""

VIEW_VECTORS: Final = (
    Path(__file__).resolve().parents[2] / "fish-rules" / "tests" / "vectors" / "view_v1.json"
)


def new_table(seed: int) -> Table:
    table = Table(seed, people=SEATS, replacement=Controller("b0-v1", NONE))
    for seat in SEATS:
        table.connect(seat, 0)
    return table


# ---------------------------------------------------------------- hello


def test_server_hello_reports_the_versions_this_server_runs() -> None:
    hello = server_hello()
    assert hello.type == "server_hello"
    assert hello.protocol_version == PROTOCOL_VERSION == 3
    assert hello.ruleset_version == RULESET_VERSION
    assert hello.rng_algorithm == RNG_ALGORITHM


def test_server_hello_round_trips_through_json() -> None:
    hello = server_hello()
    assert ServerHello.model_validate_json(hello.model_dump_json()) == hello


def test_messages_are_immutable() -> None:
    hello = server_hello()
    with pytest.raises(ValidationError, match="frozen"):
        hello.ruleset_version = "2.0"  # pyright: ignore[reportAttributeAccessIssue]


def test_every_message_has_a_unique_type_tag() -> None:
    tags = [m.model_fields["type"].annotation for m in (*CLIENT_MESSAGES, *SERVER_MESSAGES)]
    assert len(tags) == len(set(tags))


# ---------------------------------------------------------------- reading client messages


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '{"type": "client_hello", "protocol_version": 2}',
            ClientHello(type="client_hello", protocol_version=2),
        ),
        ('{"type": "join_room", "code": "AB23CD"}', JoinRoom(type="join_room", code="AB23CD")),
        ('{"type": "press", "set_id": 8, "seen": null}', Press(type="press", set_id=8, seen=None)),
        ('{"type": "press", "set_id": 0, "seen": 12}', Press(type="press", set_id=0, seen=12)),
        ('{"type": "act", "index": 912}', Act(type="act", index=912)),
        (
            '{"type": "note_answer", "answer": "declined"}',
            NoteAnswer(type="note_answer", answer="declined"),
        ),
    ],
)
def test_client_messages_are_read(raw: str, expected: object) -> None:
    assert parse_client_message(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"type": "server_hello"}',  # a server message
        '{"type": "client_hello", "protocol_version": 0}',
        '{"type": "client_hello", "protocol_version": 2, "x": 0}',  # unknown field
        '{"type": "press", "set_id": "3", "seen": null}',  # a string, not a number
        '{"type": "press", "set_id": true, "seen": null}',  # a boolean, not a number
        '{"type": "press", "set_id": 9, "seen": null}',  # no set 9
        '{"type": "press", "set_id": 0}',  # seen is required, even before the first event
        '{"type": "press", "set_id": 0, "seen": -1}',
        '{"type": "act", "index": 913}',
        '{"type": "act", "index": 1.5}',
        '{"type": "join_room", "code": "AB1CD0"}',  # 1 and 0 are not in room codes
        '{"type": "join_room", "code": "ab23cd"}',
        '{"type": "pong", "nonce": -1}',
        '{"type": "note_answer", "answer": "maybe"}',
    ],
)
def test_anything_else_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse_client_message(raw)


def test_room_codes_use_no_lookalike_characters() -> None:
    assert not set("IO01") & set(ROOM_CODE_ALPHABET)
    assert len(set(ROOM_CODE_ALPHABET)) == len(ROOM_CODE_ALPHABET) == 32


def test_the_note_taking_question_is_asked_word_for_word() -> None:
    """Research Plan §4: one question after each game, its words versioned."""
    question = note_question()
    assert (question.version, question.text) == ("v1", "Did you take notes during this game?")


def test_the_lobby_names_what_a_player_waits_for() -> None:
    lobby = Lobby(type="lobby", waiting="group", code="XYZ234", people=3)
    assert Lobby.model_validate_json(lobby.model_dump_json()) == lobby


# ---------------------------------------------------------------- the view mirrors fish-view-v1


def test_every_frozen_view_vector_is_a_view() -> None:
    cases: list[dict[str, Any]] = json.loads(VIEW_VECTORS.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 124
    for case in cases:
        assert View.model_validate(case["view"], strict=False).model_dump() == case["view"]


def test_a_view_with_an_unknown_field_is_not_a_view() -> None:
    data = view_to_data(new_table(1).view(0)) | {"seed": 1}
    with pytest.raises(ValidationError, match="extra"):
        View.model_validate(data, strict=False)


def check(table: Table, now: int) -> None:
    """Every seat's update at ``now``: its view is ``fish-view-v1`` exactly, its actions and
    presses are the table's, and it survives JSON both ways."""
    for seat in SEATS:
        message = update(table, seat, now)
        assert message.view.model_dump() == view_to_data(table.view(seat))
        actions = [decode(seat, i, table.state.phase) for i in message.actions]
        assert sorted(actions, key=encode) == sorted(table.actions(seat), key=encode)
        assert message.pressable == list(table.pressable(seat))
        assert Update.model_validate_json(message.model_dump_json()) == message


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_every_update_of_random_games_is_exact(game_seed: int, policy_seed: int) -> None:
    rng, table, now = SplitMix64(policy_seed), new_table(game_seed), 0
    check(table, now)
    for _ in range(400):
        if table.state.phase is Phase.OVER:
            break
        now += rng.below(2 * SECOND_US)
        seat = rng.choice(SEATS)
        seen = table.state.events - 1 if table.state.events else None
        if (sets := table.pressable(seat)) and rng.below(8) == 0:
            table.press(seat, rng.choice(sets), seen, now)
        elif acting := [s for s in SEATS if table.actions(s)]:
            seat = rng.choice(acting)
            table.act(seat, rng.choice(table.actions(seat)), now)
        else:
            table.advance(now)
        table.sent(now)
        check(table, now)


# ---------------------------------------------------------------- timers and bots


def test_an_update_shows_the_running_timers_with_what_they_have_left() -> None:
    table = new_table(1)
    assert [t.model_dump() for t in update(table, 0, 10 * SECOND_US).timers] == [
        {"name": "turn", "ms_left": 50_000},
    ]
    table.press(3, table.state.sets_in_play()[0], None, 20 * SECOND_US)
    timers = update(table, 0, 20 * SECOND_US + 250_000).timers
    assert [t.model_dump() for t in timers] == [{"name": "window", "ms_left": 750}]
    assert update(table, 0, 25 * SECOND_US).timers[0].ms_left == 0  # due: never negative
    table.advance(20 * SECOND_US + WINDOW_US)
    assert update(table, 0, 20 * SECOND_US + WINDOW_US).timers[0].name == "assignment"


def test_an_update_names_the_seats_bots_hold() -> None:
    table = new_table(1)
    current = table.state.current
    assert current is not None
    assert update(table, 0, 0).bots == []
    table.advance(TURN_US)  # the current player ran out of time (R.8.4)
    assert update(table, current, TURN_US).bots == [current]
    assert update(table, current, TURN_US).timers == []  # a bot's turn is not timed
