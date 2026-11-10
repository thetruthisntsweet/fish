"""The weekly integrity check (fish_server.integrity; T4.4): clean games pass, each kind of
fault is found and named with its game, and nothing is changed. Skipped without
FISH_TEST_DATABASE_URL."""

import importlib.util
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Connection, Engine, create_engine, delete, func, insert, pool, select, update

from fish_rules.cohort import in_cohort
from fish_server import db
from fish_server.integrity import Report, check, lines, main
from fish_server.settings import COHORT_SEED_VAR, admin_database_url, database_url


def _games_writer() -> ModuleType:
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


written = _games_writer()
HANDOVER = {"type": "handover", "after": 3, "at_us": 5_000_000, "seat": 1, "reason": "disconnect",
            "agent": "b1-v1", "memory": "last-k", "k": 8}  # fmt: skip


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def owner(server_env: str) -> Iterator[Engine]:
    """The database's owner, who alone can damage what the server may only add to."""
    engine = create_engine(admin_database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def faults(report: Report) -> dict[str, list[uuid.UUID | None]]:
    found: dict[str, list[uuid.UUID | None]] = {}
    for fault in report.faults:
        found.setdefault(fault.check, []).append(fault.game)
    return found


def damage(owner: Engine, statement: object) -> None:
    """Change stored rows as no part of the server can: with the append-only guards off."""
    with owner.begin() as conn:
        conn.exec_driver_sql("SET LOCAL session_replication_role = replica")
        conn.execute(statement)  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_whole_games_pass_whatever_their_standing(app: Engine) -> None:
    with app.begin() as conn:
        written.add_game(conn, 1, written.table(conn))
        written.add_game(conn, 2, written.table(conn), log=[HANDOVER])
        gone = written.table(conn)
        written.add_game(conn, 3, gone)
        written.withdraw(conn, gone[0])
        written.add_game(conn, 4, written.table(conn), ending="abandoned", max_actions=7)
        written.add_game(conn, 5, written.table(conn), ruleset="1.1")  # a staging test game
    with app.connect() as conn:
        report = check(conn, None)
    assert report.faults == []
    assert (report.games, report.replayed, report.other_ruleset) == (5, 3, 1)
    shown = "\n".join(lines(report, date(2026, 12, 14)))
    assert shown.startswith("Fish integrity check on Mon 14 Dec 2026 (Eastern)")
    assert "  records                           ok" in shown
    assert "  under another ruleset              1  (not in the corpus)" in shown
    assert shown.endswith("PASS")
    assert "draw" not in report.checks  # no seed given


def test_each_kind_of_damage_is_found_in_its_game(app: Engine, owner: Engine) -> None:
    with app.begin() as conn:
        fine, _ = written.add_game(conn, 10, written.table(conn))
        no_seat, _ = written.add_game(conn, 11, written.table(conn))
        gap, _ = written.add_game(conn, 12, written.table(conn))
        cut, _ = written.add_game(conn, 13, written.table(conn), max_actions=10, ending="finished")
        no_flags, _ = written.add_game(conn, 14, written.table(conn))
        changed, _ = written.add_game(conn, 15, written.table(conn))
        twin, _ = written.add_game(conn, 16, written.table(conn))
        strange, _ = written.add_game(conn, 17, written.table(conn), bot_delays="pilot-v9")
        noted, _ = written.add_game(conn, 18, written.table(conn, persons=5))
    damage(owner, delete(db.note_answers).where(db.note_answers.c.game_id == no_seat))
    damage(
        owner,
        delete(db.seat_consents).where(
            (db.seat_consents.c.game_id == no_seat) & (db.seat_consents.c.seat == 5)
        ),
    )
    damage(
        owner,
        delete(db.seats).where((db.seats.c.game_id == no_seat) & (db.seats.c.seat == 5)),
    )
    damage(owner, delete(db.actions).where((db.actions.c.game_id == gap) & (db.actions.c.seq == 4)))
    damage(
        owner,
        delete(db.seat_consents).where(
            (db.seat_consents.c.game_id == no_flags) & (db.seat_consents.c.seat == 2)
        ),
    )
    with app.connect() as conn:
        first = conn.execute(
            select(db.actions.c.action).where(
                (db.actions.c.game_id == fine) & (db.actions.c.seq == 0)
            )
        ).scalar_one()
    damage(  # another game's first action, in place of its own
        owner,
        update(db.actions)
        .where((db.actions.c.game_id == changed) & (db.actions.c.seq == 0))
        .values(action=first),
    )
    damage(owner, update(db.games).where(db.games.c.game_id == twin).values(seed=10))
    damage(
        owner,
        insert(db.note_answers).values(game_id=noted, seat=5, question_version="v1", answer="no"),
    )

    with app.connect() as conn:
        report = check(conn, None)
    found = faults(report)
    assert found["seats"] == [no_seat]
    assert found["actions"] == [gap]
    assert found["consent"] == [no_flags]
    assert set(found["seeds"]) == {fine, twin}
    assert found["versions"] == [strange]
    assert found["notes"] == [noted]
    assert set(found["records"]) == {cut, changed, twin}  # none replays to its recorded end
    assert fine not in found["records"]
    shown = "\n".join(lines(report, date(2026, 12, 14)))
    assert f"  actions: game {gap}: completed with" in shown
    assert f"FAIL: {len(report.faults)} faults" in shown
    assert "@" not in shown  # no address, whatever went wrong


def test_tables_of_the_wrong_group_are_found(app: Engine, owner: Engine) -> None:
    with app.begin() as conn:
        mixed = [*written.table(conn, persons=5)[:5], written.add_person(conn, cohort=True)]
        mixed_game, _ = written.add_game(conn, 20, mixed)
        marked, _ = written.add_game(conn, 21, written.table(conn))
        room, _ = written.add_game(conn, 22, written.table(conn))
    damage(owner, update(db.games).where(db.games.c.game_id == marked).values(cohort_table=True))
    damage(
        owner,
        update(db.games)
        .where(db.games.c.game_id == room)
        .values(matchmaking="group", cohort_table=True),
    )
    with app.connect() as conn:
        found = faults(check(conn, None))
    assert set(found["cohort"]) == {mixed_game, marked, room}


def test_a_stale_game_and_a_person_at_two_tables_are_found(app: Engine) -> None:
    with app.begin() as conn:
        people = written.table(conn)
        ago = int((datetime.now(UTC) - written.START).total_seconds() // 60) - 600  # 10 hours
        first, _ = written.add_game(conn, 30, people, ending=None, minutes=ago)  # long quiet
        again = [people[0], *written.table(conn)[1:]]
        second, _ = written.add_game(conn, 31, again, minutes=ago + 1)
        # Handed to a bot after 5 seconds, then seated again a minute later: allowed.
        left = written.table(conn)
        written.add_game(conn, 32, left, log=[HANDOVER], minutes=ago + 100)
        written.add_game(conn, 33, [left[1], *written.table(conn)[1:]], minutes=ago + 101)
        written.add_game(conn, 34, written.table(conn), ending=None, minutes=ago + 599)  # live
    with app.connect() as conn:
        found = faults(check(conn, None))
    assert found["stale"] == [first]
    assert found["two tables"] == [first]
    assert second not in found.get("records", [])


def test_a_player_in_the_wrong_group_is_found(app: Engine) -> None:
    seed = 2026
    with app.begin() as conn:
        for _ in range(40):
            person = uuid.uuid4()
            number = conn.execute(select(db.signup_numbers.next_value())).scalar_one()
            conn.execute(
                insert(db.players).values(
                    player_id=person, signup_number=number, cohort=in_cohort(seed, number)
                )
            )
    with app.connect() as conn:
        assert check(conn, seed).faults == []
        wrong = check(conn, seed + 1)
    assert {f.check for f in wrong.faults} == {"draw"}
    assert all(f.game is None for f in wrong.faults)
    assert "  draw: a player: sign-up number " in "\n".join(lines(wrong, date(2026, 12, 14)))


def test_the_command_exits_by_what_it_found_and_changes_nothing(
    app: Engine, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COHORT_SEED_VAR, "2026")

    def rows(conn: Connection) -> list[int]:
        return [
            conn.execute(select(func.count()).select_from(table)).scalar_one()
            for table in db.metadata.sorted_tables
        ]

    assert main([], create_engine(database_url(), poolclass=pool.NullPool)) == 0
    assert capsys.readouterr().out.endswith("PASS\n")
    with app.begin() as conn:
        game, _ = written.add_game(conn, 40, written.table(conn), bot_delays="pilot-v9")
    with app.connect() as conn:
        before = rows(conn)
    assert main([], create_engine(database_url(), poolclass=pool.NullPool)) == 1
    out = capsys.readouterr().out
    assert f"  versions: game {game}: unknown bot delay table pilot-v9" in out
    with app.connect() as conn:
        assert rows(conn) == before
