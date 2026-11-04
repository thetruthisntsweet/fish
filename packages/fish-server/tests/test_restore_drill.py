"""Tests for fish_server.restore_drill (T2.1 subtask 13, T3.6): the marker, and the check
that a restored copy holds every row there was at the marker and still exports the corpus.
Games are written the way the export tests write them (test_corpus_export.py)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, pool, text

from fish_server.restore_drill import (
    EXPORTED,
    TABLE,
    check,
    cleanup,
    count_markers,
    damage,
    held,
    main,
    mark,
    marked,
)


def _games() -> ModuleType:
    """test_corpus_export.py, for its way of writing games."""
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GAMES = _games()


@pytest.fixture
def owner(server_env: str) -> Engine:
    """The migrated database as its owner, as the drill runs it (FISH_ADMIN_DATABASE_URL)."""
    return create_engine(server_env, poolclass=pool.NullPool)


def two_games(engine: Engine) -> list[object]:
    """Two corpus games; returns the people of the first."""
    with engine.begin() as conn:
        first = GAMES.table(conn)
        GAMES.add_game(conn, 5, first)
        GAMES.add_game(conn, 6, GAMES.table(conn), minutes=1)
    return first


def test_mark_records_what_the_database_holds(owner: Engine) -> None:
    two_games(owner)
    at, counts = mark(owner)
    assert at
    assert counts["games"] == 2
    assert counts["seats"] == 12
    assert counts["players"] == 12
    assert counts["actions"] > 0
    assert counts[EXPORTED] == 2
    assert marked(owner) == counts
    assert count_markers(owner) == 1


def test_the_drill_passes_on_a_copy_holding_everything_and_fails_on_damage(owner: Engine) -> None:
    two_games(owner)
    mark(owner)
    with owner.begin() as conn:  # games played after the marker change nothing
        GAMES.add_game(conn, 7, GAMES.table(conn), minutes=2)
    problems, counts = check(owner)
    assert problems == []
    assert counts[EXPORTED] == 3
    assert damage(owner) == 1
    assert check(owner) == (["marker not found."], {})
    cleanup(owner)
    assert count_markers(owner) == 0


def test_a_copy_with_fewer_rows_fails_naming_the_table(owner: Engine) -> None:
    two_games(owner)
    mark(owner)
    with owner.begin() as conn:  # as if the restore had lost a game written before the marker
        conn.execute(text(f"UPDATE {TABLE} SET counts = jsonb_set(counts, '{{games}}', '3')"))
    problems, _ = check(owner)
    assert problems == ["games: 2, fewer than the 3 at mark."]


def test_a_withdrawal_after_the_marker_is_named_as_the_likely_reason(owner: Engine) -> None:
    first = two_games(owner)
    mark(owner)
    with owner.begin() as conn:
        GAMES.withdraw(conn, first[0])
    problems, counts = check(owner)
    assert counts[EXPORTED] == 1
    assert problems == [
        f"{EXPORTED}: 1, fewer than the 2 at mark (a withdrawal since the marker would explain it)."
    ]


def test_an_export_that_does_not_build_fails(owner: Engine) -> None:
    two_games(owner)
    mark(owner)
    with owner.begin() as conn:
        GAMES.add_game(conn, 8, GAMES.table(conn), minutes=3, ruleset="1.0")
    problems, _ = check(owner)
    assert len(problems) == 1
    assert problems[0].startswith("the corpus export does not build: game")


def test_a_marker_from_before_counts_must_be_written_again(owner: Engine) -> None:
    with owner.begin() as conn:  # the drill table as the first drill (14 October) left it
        conn.execute(
            text(
                f"CREATE TABLE {TABLE} (id serial PRIMARY KEY, label text NOT NULL,"
                " created_at timestamptz NOT NULL DEFAULT now())"
            )
        )
        conn.execute(text(f"INSERT INTO {TABLE} (label) VALUES ('restore-drill-marker')"))
    assert marked(owner) is None
    assert check(owner)[0] == [
        "the marker records no counts: write a new one with this version (mark)."
    ]
    mark(owner)  # adds the column to the old table
    assert check(owner)[0] == []


def test_held_counts_every_append_only_table(owner: Engine) -> None:
    counts = held(owner)
    assert counts == dict.fromkeys(counts, 0)
    assert {"players", "consents", "withdrawals", "games", "actions", EXPORTED} <= set(counts)


@pytest.mark.usefixtures("owner")
def test_the_command_line(server_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--url", server_env]) == 1
    assert "FAIL: marker not found." in capsys.readouterr().out
    assert main(["mark", "--url", server_env]) == 0
    out = capsys.readouterr().out
    assert "Marker written" in out
    assert "Holding: players 0," in out
    assert main(["check", "--url", server_env]) == 0
    out = capsys.readouterr().out
    assert f"{EXPORTED} 0." in out
    assert "PASS: marker present, every row there at mark, and the corpus exports." in out
    assert main(["damage", "--url", server_env]) == 0
    assert "Deleted 1" in capsys.readouterr().out
    assert main(["cleanup", "--url", server_env]) == 0
    assert "Dropped" in capsys.readouterr().out


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["explode"])


def test_counts_are_stored_as_json(owner: Engine) -> None:
    _, counts = mark(owner)
    with owner.connect() as conn:
        stored = conn.execute(text(f"SELECT counts::text FROM {TABLE}")).scalar_one()
    assert json.loads(stored) == counts
