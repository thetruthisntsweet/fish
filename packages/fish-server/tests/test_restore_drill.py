"""Tests for fish_server.restore_drill (T2.1 subtask 13)."""

import pytest
from sqlalchemy import create_engine, pool

from fish_server.restore_drill import cleanup, count_markers, damage, main, mark


def test_the_full_drill_on_one_database(fresh_database_url: str) -> None:
    engine = create_engine(fresh_database_url, poolclass=pool.NullPool)
    assert count_markers(engine) == 0  # no drill table yet
    assert mark(engine)
    assert count_markers(engine) == 1
    assert damage(engine) == 1
    assert count_markers(engine) == 0
    mark(engine)
    cleanup(engine)
    assert count_markers(engine) == 0
    engine.dispose()


def test_command_line_check_fails_then_passes(
    fresh_database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", "--url", fresh_database_url]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert main(["mark", "--url", fresh_database_url]) == 0
    assert "Marker written" in capsys.readouterr().out
    assert main(["check", "--url", fresh_database_url]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["damage", "--url", fresh_database_url]) == 0
    assert "Deleted 1" in capsys.readouterr().out
    assert main(["cleanup", "--url", fresh_database_url]) == 0
    assert "Dropped" in capsys.readouterr().out


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["explode"])
