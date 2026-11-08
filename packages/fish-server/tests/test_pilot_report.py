"""What the pilot measured (fish_server.pilot_report; T4.2): only the games from ``--since``,
times taken from their corpus records, response times split by kind and counted only for
people, and nothing that names a game, seat or person. The database tests are skipped without
FISH_TEST_DATABASE_URL."""

import importlib.util
import json
import re
from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Connection, Engine, create_engine, pool, select

from fish_server import db
from fish_server.pilot_report import KIND_OF, KINDS, figures, five_minutes, main, percentiles, read
from fish_server.settings import database_url


def _games_writer() -> ModuleType:
    """The export tests' writer of real website games, so the report reads what they export."""
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


written = _games_writer()
TYPES: dict[str, str] = {action.__name__: kind for action, kind in KIND_OF.items()}
"""Each stored action type's kind, by the name its JSON carries."""
DAY = 24 * 60
"""Minutes in a day: ``add_game`` starts games this many minutes after 1 Dec, 20:00 UTC."""


# ---------------------------------------------------------------- figures


def test_percentiles_run_from_the_least_to_the_most() -> None:
    values = list(range(1000, 0, -10))  # 100 values, unsorted
    cut = percentiles(values)
    assert len(cut) == 101
    assert (cut[0], cut[50], cut[100]) == (10, 505, 1000)
    assert cut == sorted(cut)
    assert percentiles([7]) == [7] * 101
    assert percentiles([]) == []


def test_m3s_game_length_is_rounded_to_five_minutes() -> None:
    assert [five_minutes(m) for m in (22.4, 22.5, 24.9, 27.4, 27.6)] == [20, 25, 25, 25, 30]


def test_every_kind_the_bots_need_has_a_name() -> None:
    assert set(KIND_OF.values()) == set(KINDS)


# ---------------------------------------------------------------- from the database


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def _stored(conn: Connection, game_id: object) -> list[dict[str, object]]:
    a = db.actions.c
    rows = conn.execute(
        select(a.action, a.cause_seat, a.received_us, a.sent_us)
        .where(a.game_id == game_id)
        .order_by(a.seq)
    ).mappings()
    return [dict(row) for row in rows]


def _type(row: dict[str, object]) -> str:
    action = row["action"]
    assert isinstance(action, dict)
    return str(action["type"])  # pyright: ignore[reportUnknownArgumentType]


def test_the_report_reads_the_pilots_games_as_the_export_does(app: Engine) -> None:
    log = [
        {"type": "rtt", "after": 1, "at_us": 1, "seat": 0, "rtt_us": 40_000},
        {"type": "rtt", "after": 2, "at_us": 2, "seat": 1, "rtt_us": 60_000},
        {"type": "connection", "after": 2, "at_us": 3, "seat": 1, "state": "disconnected"},
        {"type": "rejected", "after": 3, "at_us": 4, "seat": 2, "input": {}, "reason": "stale"},
        {
            "type": "handover",
            "after": 3,
            "at_us": 5,
            "seat": 1,
            "reason": "disconnect",
            "agent": "b1-v1",
            "memory": "last-k",
            "k": 8,
        },
    ]
    with app.begin() as conn:
        written.add_game(conn, 30, written.table(conn), minutes=-2 * DAY)  # 29 Nov: a test game
        counted = [
            written.add_game(conn, seed, written.table(conn), minutes=DAY)[0]
            for seed in (31, 32, 33)
        ]
        with_bots, _ = written.add_game(conn, 34, written.table(conn, persons=4), log=log)
        written.add_game(conn, 35, written.table(conn), ending="abandoned")
        written.add_game(conn, 36, written.table(conn), ending=None)
        games = {g: _stored(conn, g) for g in [*counted, with_bots]}
        ends = dict(
            conn.execute(
                select(db.game_endings.c.game_id, db.game_endings.c.completion).where(
                    db.game_endings.c.game_id.in_(list(games))
                )
            ).all()
        )

    with app.connect() as conn:
        pilot = read(conn, date(2026, 12, 1))
        everything = read(conn, None)

    assert pilot.standing == Counter(exported=4, abandoned=1, not_ended=1)
    assert everything.standing["exported"] == 5  # the 29 November game too

    finished = [g for g in games if ends[g] == "finished"]
    assert finished
    assert sorted(pilot.lengths_us) == sorted(int(games[g][-1]["sent_us"]) for g in finished)  # pyright: ignore[reportArgumentType]
    window = 0
    for g in finished:
        opened = 0
        for row in games[g]:
            if _type(row) == "OpenWindow":
                opened = int(row["received_us"])  # pyright: ignore[reportArgumentType]
            elif _type(row) == "CloseWindow":
                window += int(row["received_us"]) - opened  # pyright: ignore[reportArgumentType]
    assert pilot.window_us == window > 0

    # Every person's input of each kind has a time, and no bot's: in the game with bots, B1
    # holds seats 4 and 5 from the start, and seat 1 after its handover at action 3.
    expected: Counter[str] = Counter()
    for g, rows in games.items():
        for n, row in enumerate(rows):
            seat = row["cause_seat"]
            bot = g == with_bots and (seat in (4, 5) or (seat == 1 and n >= 3))
            if _type(row) in TYPES and isinstance(seat, int) and not bot:
                expected[TYPES[_type(row)]] += 1
    assert {kind: len(v) for kind, v in pilot.responses_us.items()} == {
        kind: expected[kind] for kind in KINDS
    }
    assert all(expected[kind] for kind in KINDS)

    assert pilot.round_trips_us == [40_000, 60_000]
    assert pilot.handovers == Counter(disconnect=1)
    assert pilot.games_handed_over == 1
    assert pilot.disconnections == 1
    assert pilot.rejected == Counter(stale=1)


def test_the_command_prints_the_report_and_writes_the_percentiles(
    app: Engine, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with app.begin() as conn:
        ids = [written.add_game(conn, s, written.table(conn), minutes=DAY)[0] for s in (41, 42)]
        players = conn.execute(select(db.players.c.player_id)).scalars().all()
    out = tmp_path / "pilot.json"
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    assert main(["--since", "2026-12-01", "--out", str(out)], engine) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("Fish pilot report: started from Tue 1 Dec 2026 (Eastern)\n")
    assert "  in the corpus                       2" in printed
    for label in KINDS.values():
        assert f"\n  {label:<30}" in printed
    data = json.loads(out.read_text())
    assert data["since"] == "2026-12-01"
    assert data["games"]["exported"] == 2
    for kind in KINDS:
        cut = data["response_times_us"][kind]["percentiles"]
        assert len(cut) == 101
        assert cut == sorted(cut)

    # Aggregates only: no game or player ID, no address, no seed.
    for text in (printed, out.read_text()):
        assert "@" not in text
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text)
        for name in [*ids, *players]:
            assert str(name) not in text

    with pytest.raises(SystemExit):  # never overwrites
        main(["--out", str(out)], engine)
    assert "exists already" in capsys.readouterr().err


def test_nothing_played_yet_reads_cleanly(app: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    assert main(["--since", "2026-12-01"], engine) == 0
    printed = capsys.readouterr().out
    assert "  in the corpus                       0" in printed
    assert "  no finished games" in printed
    assert "round trip" not in printed
    with engine.connect() as conn:
        data = figures(read(conn, None))
    assert data["window_share"] is None
    assert data["round_trip_us"] == []
