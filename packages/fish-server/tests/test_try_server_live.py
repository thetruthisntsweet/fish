"""``scripts/try_server.py``'s socket check against the real server on a real port (T4.3): a
room made and left while tables are open, and refused in ``/study``'s words while they are
not, as on the study's site before it opens. Skipped without FISH_TEST_DATABASE_URL."""

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine

from fish_server.settings import OPENS_VAR


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load(Path(__file__).parents[3] / "scripts" / "try_server.py", "try_server_live")
E2E = _load(Path(__file__).with_name("test_end_to_end.py"), "e2e_live")
app = E2E.app
site = E2E.site


def test_a_room_is_made_while_open_and_refused_in_the_sites_words_while_closed(
    app: Engine,
    site: tuple[str, object, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ((_, session),) = E2E.sign_up(app, site, 1)
    base = f"http://{site[0]}"
    assert SCRIPT.tables_notice(base) is None
    asyncio.run(SCRIPT.socket(base, session, None))
    assert "room: " in capsys.readouterr().out

    monkeypatch.setenv(OPENS_VAR, "2099-01-01")  # the server reads it at every request
    notice = SCRIPT.tables_notice(base)
    assert notice == (
        "The study opens on Thursday 1 January 2099. Until then, no games can be played here."
    )
    asyncio.run(SCRIPT.socket(base, session, notice))
    assert "'code': 'not_now'" in capsys.readouterr().out
    with pytest.raises(RuntimeError, match="did not refuse the room as /study says"):
        asyncio.run(SCRIPT.socket(base, session, "Some other words."))
