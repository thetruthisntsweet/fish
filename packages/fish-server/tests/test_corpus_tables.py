"""Tests for the corpus tables (fish_server.db, migration 0003; docs/corpus.md §2 to §5).

Against a real PostgreSQL: the migration creates exactly the tables the metadata describes,
the server's login can write and read a whole game, the play and consent tables refuse every
change even from the owner, and the constraints reject what the record format rejects.
Skipped without FISH_TEST_DATABASE_URL, like every database test.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, Table, create_engine, func, insert, inspect, pool, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from fish_rules.codec import action_to_data
from fish_rules.playout import random_game
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.settings import database_url

STARTED = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)


@pytest.fixture
def owner(server_env: str) -> Iterator[Engine]:
    engine = create_engine(server_env, poolclass=pool.NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    """The server's own login, which only reads and inserts."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def write_game(engine: Engine) -> dict[str, Any]:
    """Write one short game with every kind of row, as the server would. Returns its ids."""
    people = [uuid.uuid4() for _ in range(5)]
    consents: list[int] = []
    game_id = uuid.uuid4()
    actions = random_game(7, 8)[:12]
    with engine.begin() as conn:
        for person in people:
            number = conn.execute(select(db.signup_numbers.next_value())).scalar_one()
            conn.execute(
                insert(db.players).values(player_id=person, signup_number=number, cohort=False)
            )
            conn.execute(
                insert(db.player_contacts).values(player_id=person, email=f"{person}@example.org")
            )
            consents.append(
                conn.execute(
                    insert(db.consents)
                    .values(player_id=person, version="v1.0", **CONFIRMED)
                    .returning(db.consents.c.consent_id)
                ).scalar_one()
            )
        conn.execute(
            insert(db.games).values(
                game_id=game_id,
                seed=2**64 - 1,
                ruleset=RULESET_VERSION,
                action_encoding="fish-actions-v1",
                state_encoding="fish-state-v1",
                server_commit="abc1234",
                protocol_version=1,
                matchmaking="solo",
                cohort_table=False,
                started_at=STARTED,
            )
        )
        for seat, person in enumerate(people):
            conn.execute(
                insert(db.seats).values(
                    game_id=game_id, seat=seat, player_id=person, memory="human"
                )
            )
        for seat, (person, consent) in enumerate(zip(people[:4], consents, strict=False)):
            conn.execute(
                insert(db.seat_consents).values(
                    game_id=game_id, seat=seat, player_id=person, consent_id=consent,
                    version="v1.0", **CONFIRMED,
                )
            )  # fmt: skip
        conn.execute(insert(db.withdrawals).values(player_id=people[3], channel="email"))
        conn.execute(
            insert(db.seats).values(game_id=game_id, seat=5, agent="b1-v1", memory="last-k", k=8)
        )
        for seq, action in enumerate(actions):
            seat = getattr(action, "seat", None)
            conn.execute(
                insert(db.actions).values(
                    game_id=game_id,
                    seq=seq,
                    action=action_to_data(action),
                    cause_seat=seat,
                    cause_timer=None if seat is not None else "window",
                    received_us=1_000 * seq,
                    sent_us=1_000 * seq + 50,
                )
            )
        conn.execute(
            insert(db.server_log).values(
                game_id=game_id, after_seq=0, at_us=0, seat=0, type="rtt", data={"rtt_us": 40_000}
            )
        )
        conn.execute(
            insert(db.note_answers).values(
                game_id=game_id, seat=0, question_version="v1", answer="no"
            )
        )
        conn.execute(insert(db.game_endings).values(game_id=game_id, completion="abandoned"))
    return {"game_id": game_id, "people": people, "actions": actions, "consents": consents}


# ---------------------------------------------------------------- the schema


def test_the_migration_creates_exactly_the_metadata(owner: Engine) -> None:
    """Migration 0003 and fish_server.db describe the same tables, columns, types,
    constraints and indexes: autogenerate finds nothing to change."""
    with owner.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), db.metadata) == []
    tables = set(inspect(owner).get_table_names())
    assert tables == set(db.metadata.tables) | {"alembic_version"}
    with owner.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('signup_numbers')")).scalar() is not None


def test_every_table_but_the_private_ones_is_append_only() -> None:
    assert set(db.APPEND_ONLY) == set(db.metadata.tables) - set(db.PRIVATE)


# ---------------------------------------------------------------- writing and reading


def test_the_server_login_writes_and_reads_a_whole_game(app: Engine) -> None:
    written = write_game(app)
    with app.connect() as conn:
        stored = conn.execute(
            select(db.actions.c.action)
            .where(db.actions.c.game_id == written["game_id"])
            .order_by(db.actions.c.seq)
        ).scalars()
        assert list(stored) == [action_to_data(a) for a in written["actions"]]
        seed = conn.execute(select(db.games.c.seed)).scalar_one()
        assert int(seed) == 2**64 - 1
        numbers = conn.execute(select(db.players.c.signup_number)).scalars().all()
        assert sorted(numbers) == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("table", db.APPEND_ONLY)
@pytest.mark.parametrize("statement", ["UPDATE {t} SET {c} = {c}", "DELETE FROM {t}"])
def test_rows_cannot_be_changed_even_by_the_owner(
    owner: Engine, table: str, statement: str
) -> None:
    """docs/corpus.md §1: written once. The triggers refuse every role."""
    write_game(owner)
    column = next(iter(db.metadata.tables[table].columns)).name
    with pytest.raises(DBAPIError, match="append-only"), owner.begin() as conn:
        conn.execute(text(statement.format(t=table, c=column)))


@pytest.mark.parametrize("table", db.APPEND_ONLY)
def test_tables_cannot_be_truncated_even_by_the_owner(owner: Engine, table: str) -> None:
    write_game(owner)
    with pytest.raises(DBAPIError), owner.begin() as conn:
        conn.execute(text(f"TRUNCATE {table} CASCADE"))
    with owner.connect() as conn:
        assert conn.execute(select(func.count()).select_from(db.metadata.tables[table])).scalar()


def test_a_contact_address_can_be_removed(owner: Engine) -> None:
    """§7: contact data is the one thing that may be deleted, by the owner on request."""
    person = write_game(owner)["people"][0]
    with owner.begin() as conn:
        conn.execute(db.player_contacts.delete().where(db.player_contacts.c.player_id == person))
        assert conn.execute(select(func.count()).select_from(db.player_contacts)).scalar() == 4


# ---------------------------------------------------------------- constraints


CONFIRMED = {"us_resident_adult": True, "agrees": True, "no_outside_communication": True}


def _consent(**values: object) -> tuple[Table, dict[str, object]]:
    return db.consents, {"player_id": "PERSON", "version": "v1.0"} | CONFIRMED | values


def _seat_consent(**values: object) -> tuple[Table, dict[str, object]]:
    base = {"seat": 4, "player_id": "SEAT4", "consent_id": "CONSENT4", "version": "v1.0"}
    return db.seat_consents, base | CONFIRMED | values


def _player(**values: object) -> tuple[Table, dict[str, object]]:
    return db.players, {"player_id": uuid.uuid4(), "signup_number": 99, "cohort": False} | values


def _game(**values: object) -> tuple[Table, dict[str, object]]:
    base: dict[str, object] = {
        "game_id": uuid.uuid4(),
        "seed": 1,
        "ruleset": RULESET_VERSION,
        "action_encoding": "fish-actions-v1",
        "state_encoding": "fish-state-v1",
        "server_commit": "abc1234",
        "protocol_version": 1,
        "matchmaking": "solo",
        "cohort_table": False,
        "started_at": STARTED,
    }
    return db.games, base | values


def _seat(**values: object) -> tuple[Table, dict[str, object]]:
    base = {"game_id": "OTHER_GAME", "seat": 5, "agent": "b1-v1", "memory": "none", "k": None}
    return db.seats, base | values


def _action(**values: object) -> tuple[Table, dict[str, object]]:
    base: dict[str, object] = {
        "seq": 99,
        "action": {"type": "CloseWindow"},
        "cause_seat": None,
        "cause_timer": "window",
        "received_us": 5,
        "sent_us": 6,
    }
    return db.actions, base | values


def _log(**values: object) -> tuple[Table, dict[str, object]]:
    base = {"after_seq": 0, "at_us": 0, "seat": 0, "type": "rtt", "data": {"rtt_us": 1}}
    return db.server_log, base | values


BAD: list[tuple[str, tuple[Table, dict[str, object]], str]] = [
    ("seed too large", _game(seed=2**64), "ck_games_seed"),
    ("seed negative", _game(seed=-1), "ck_games_seed"),
    ("matchmaking", _game(matchmaking="friends"), "ck_games_matchmaking"),
    ("protocol", _game(protocol_version=0), "ck_games_protocol_version"),
    ("signup number", _player(signup_number=-1), "ck_players_signup_number"),
    ("signup taken", _player(signup_number=0), "uq_players_signup_number"),
    ("seat 6", _seat(seat=6), "ck_seats_seat"),
    ("seat taken", _seat(game_id="GAME", seat=0), "pk_seats"),
    ("person and agent", _seat(seat=5, player_id="PERSON", memory="human"), "ck_seats_controller"),
    ("person memory", _seat(agent=None, player_id="OTHER", memory="full"), "ck_seats_controller"),
    ("last-k without k", _seat(memory="last-k"), "ck_seats_controller"),
    ("k without last-k", _seat(memory="full", k=8), "ck_seats_controller"),
    ("k zero", _seat(memory="last-k", k=0), "ck_seats_controller"),
    ("bot memory human", _seat(memory="human"), "ck_seats_controller"),
    ("seq taken", _action(seq=0), "pk_actions"),
    ("seq negative", _action(seq=-1), "ck_actions_seq"),
    ("two causes", _action(cause_seat=0), "ck_actions_cause"),
    ("no cause", _action(cause_timer=None), "ck_actions_cause"),
    ("cause seat", _action(cause_seat=7, cause_timer=None), "ck_actions_cause"),
    ("cause timer", _action(cause_timer="turn"), "ck_actions_cause"),
    ("sent first", _action(received_us=9, sent_us=8), "ck_actions_times"),
    ("log type", _log(type="chat"), "ck_server_log_type"),
    ("log seat", _log(seat=9), "ck_server_log_seat"),
    ("log position", _log(after_seq=-1), "ck_server_log_position"),
    (
        "note answer",
        (db.note_answers, {"seat": 1, "question_version": "v1", "answer": "maybe"}),
        "ck_note_answers_answer",
    ),
    (
        "note for no seat",
        (
            db.note_answers,
            {"game_id": "OTHER_GAME", "seat": 1, "question_version": "v1", "answer": "no"},
        ),
        "fk_note_answers_game_id_seat_seats",
    ),
    ("second ending", (db.game_endings, {"completion": "finished"}), "pk_game_endings"),
    ("consent unticked", _consent(agrees=False), "ck_consents_confirmed"),
    ("consent not adult", _consent(us_resident_adult=False), "ck_consents_confirmed"),
    ("consent version", _consent(version="1.0"), "ck_consents_version"),
    (
        "withdrawal channel",
        (db.withdrawals, {"player_id": "PERSON", "channel": "fax"}),
        "ck_withdrawals_channel",
    ),
    (
        "seat flags unticked",
        _seat_consent(no_outside_communication=False),
        "ck_seat_consents_confirmed",
    ),
    (
        "seat flags twice",
        _seat_consent(seat=0, player_id="PERSON", consent_id="CONSENT"),
        "pk_seat_consents",
    ),
    (
        "another's acceptance",
        _seat_consent(consent_id="CONSENT"),
        "fk_seat_consents_consent_id_player_id_version_consents",
    ),
    (
        "another's seat",
        _seat_consent(player_id="OTHER", consent_id="CONSENT1"),
        "fk_seat_consents_game_id_seat_player_id_seats",
    ),
    (
        "acceptance of another version",
        _seat_consent(version="v1.1"),
        "fk_seat_consents_consent_id_player_id_version_consents",
    ),
    ("a bot's seat", _seat_consent(seat=5), "fk_seat_consents_game_id_seat_player_id_seats"),
    (
        "completion",
        (db.game_endings, {"game_id": "OTHER_GAME", "completion": "done"}),
        "ck_game_endings",
    ),
]


@pytest.mark.parametrize(("row", "constraint"), [b[1:] for b in BAD], ids=[b[0] for b in BAD])
def test_constraints_reject_what_the_record_format_rejects(
    app: Engine, row: tuple[Table, dict[str, object]], constraint: str
) -> None:
    written = write_game(app)
    table, values = row
    other_game = _game()[1]
    with app.begin() as conn:
        conn.execute(insert(db.games).values(other_game))
    filled: dict[str, object] = {}
    if "game_id" in table.columns:
        filled["game_id"] = written["game_id"]
    for key, value in values.items():
        if value == "PERSON":
            value = written["people"][0]
        elif value == "OTHER":
            value = written["people"][1]
        elif value == "OTHER_GAME":
            value = other_game["game_id"]
        elif value == "GAME":
            value = written["game_id"]
        elif value == "SEAT4":
            value = written["people"][4]
        elif value == "CONSENT":
            value = written["consents"][0]
        elif value == "CONSENT1":
            value = written["consents"][1]
        elif value == "CONSENT4":
            value = written["consents"][4]
        filled[key] = value
    with pytest.raises(IntegrityError, match=constraint), app.begin() as conn:
        conn.execute(insert(table).values(filled))


def test_a_person_holds_at_most_one_seat_of_a_game(app: Engine) -> None:
    person = write_game(app)["people"][0]
    game = _game()[1]
    with app.begin() as conn:
        conn.execute(insert(db.games).values(game))
        row = {"game_id": game["game_id"], "player_id": person, "memory": "human"}
        conn.execute(insert(db.seats).values(row | {"seat": 0}))
    with pytest.raises(IntegrityError, match="uq_seats_game_id_player_id"), app.begin() as conn:
        conn.execute(insert(db.seats).values(row | {"seat": 1}))
