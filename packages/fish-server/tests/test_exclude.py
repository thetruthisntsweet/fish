"""Leaving a game out after a fault (fish_server.exclude; T4.4, docs/runbooks/collection.md
§4): a record with its reason, which takes the game out of the corpus and lets the export and
the integrity check go on, and which nothing can change afterwards. Skipped without
FISH_TEST_DATABASE_URL."""

import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, delete, pool, select, update
from sqlalchemy.exc import DBAPIError

from fish_rules.corpus import read_corpus_record
from fish_server import db
from fish_server.corpus_export import ExportError, export, membership
from fish_server.exclude import main
from fish_server.integrity import check
from fish_server.settings import admin_database_url, database_url
from fish_server.stats import read, report


def _games_writer() -> ModuleType:
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


written = _games_writer()
REASON = "D140: recorded as finished after 10 actions; it cannot be replayed"


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def run(*args: str) -> int:
    return main(list(args), create_engine(database_url(), poolclass=pool.NullPool))


def test_an_excluded_game_leaves_the_corpus_and_stops_blocking_it(
    app: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        written.add_game(conn, 1, written.table(conn))
        bad, _ = written.add_game(conn, 2, written.table(conn), max_actions=10, ending="finished")
    with app.connect() as conn, pytest.raises(ExportError):
        export(conn)  # one game that does not read stops the whole export
    with app.connect() as conn:
        assert [f.game for f in check(conn, None).faults] == [bad]

    assert run(str(bad), "--reason", REASON) == 0
    assert f"Excluded game {bad}, which was in the corpus." in capsys.readouterr().out

    with app.connect() as conn:
        records, summary = export(conn)
        assert membership(conn)[bad] == "excluded"
        checked = check(conn, None)
        people, games, today = read(conn, "v1.0")
        stored = conn.execute(select(db.game_exclusions.c.reason)).scalar_one()
    assert [read_corpus_record(r).seed for r in records] == [1]
    assert summary.excluded == 1
    assert "left out, excluded after a fault: 1" in summary.lines()
    assert (checked.faults, checked.excluded) == ([], 1)
    assert [f.game for f in checked.known] == [bad]  # still seen, no longer failing
    assert "excluded after a fault 1" in "\n".join(report(people, games, today, "v1.0"))
    assert stored == REASON


def test_only_a_stored_game_with_a_real_reason_once(
    app: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        game, _ = written.add_game(conn, 3, written.table(conn))
    assert run(str(uuid.uuid4()), "--reason", REASON) == 1
    assert "nothing recorded" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run(str(game), "--reason", "bad")
    with pytest.raises(SystemExit):
        run("not-a-game", "--reason", REASON)
    capsys.readouterr()
    assert run(str(game), "--reason", REASON) == 0
    assert run(str(game), "--reason", "D141: something else entirely") == 0
    assert f"is excluded already ({REASON})" in capsys.readouterr().out
    with app.connect() as conn:
        assert conn.execute(select(db.game_exclusions.c.reason)).scalars().all() == [REASON]


def test_an_exclusion_cannot_be_changed_or_removed_even_by_the_owner(app: Engine) -> None:
    with app.begin() as conn:
        game, _ = written.add_game(conn, 4, written.table(conn))
    assert run(str(game), "--reason", REASON) == 0
    owner = create_engine(admin_database_url(), poolclass=pool.NullPool)
    for statement in (
        update(db.game_exclusions).values(reason="something else, long enough"),
        delete(db.game_exclusions),
    ):
        with pytest.raises(DBAPIError), owner.begin() as conn:
            conn.execute(statement)
    owner.dispose()
