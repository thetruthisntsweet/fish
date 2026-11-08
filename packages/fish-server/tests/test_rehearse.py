"""``scripts/rehearse.py`` (T4.2; docs/runbooks/rehearsal.md) against the real server on a real
port: six signed-in test players make and join a private room and play a whole game by the
rules, so the rehearsal on staging will play. Its waits are sped up here. Skipped without
FISH_TEST_DATABASE_URL."""

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, func, select

from fish_rules.corpus import read_corpus_record
from fish_server import db
from fish_server.corpus_export import export


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load(Path(__file__).parents[3] / "scripts" / "rehearse.py", "rehearse")
E2E = _load(Path(__file__).with_name("test_end_to_end.py"), "e2e")
app = E2E.app
site = E2E.site


def test_six_test_players_play_a_whole_game_at_a_room(
    app: Engine, site: tuple[str, object, object], capsys: pytest.CaptureFixture[str]
) -> None:
    people = E2E.sign_up(app, site, 6)
    sessions = [token for _, token in people]
    waits = asyncio.run(SCRIPT.rehearse(f"http://{site[0]}", sessions, 1, 0, speed=40))
    assert "game 1: " in capsys.readouterr().out
    assert all(waits.by_kind[kind] for kind in ("turn", "press", "assign"))
    E2E.wait_for(app, db.game_endings, 1)
    with app.connect() as conn:
        (record,), _ = export(conn)
        notes = conn.execute(select(func.count()).select_from(db.note_answers)).scalar_one()
    game = read_corpus_record(record)
    assert game.game.matchmaking == "group"  # a room
    assert game.game.completion in ("finished", "unfinished")
    assert not any(row.type == "handover" for row in game.log)
    assert notes == 6


def test_the_sessions_file_needs_six_different_values(tmp_path: Path) -> None:
    file = tmp_path / "sessions.txt"
    file.write_text("a\nb\nc\nd\ne\ne\n")
    with pytest.raises(SystemExit):
        SCRIPT.main(["http://x", "--sessions", str(file)])
