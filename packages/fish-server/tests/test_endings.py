"""How a game's ending is written (T3.2; docs/corpus.md §3): only after a check that its stored
actions have no gap, ``abandoned`` if they do; and the sweep that marks ``abandoned`` the
games a crash or a restart left without one, never a game still being played. Skipped
without FISH_TEST_DATABASE_URL."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, Engine, create_engine, insert, pool, select

from fish_server import db
from fish_server.games import QUIET, abandon_quiet, start_game, write_ending
from fish_server.hub import Hub
from fish_server.lobby import Formed, Player
from fish_server.settings import database_url
from fish_server.signin import player_for


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def a_game(
    conn: Connection, *, started: datetime, actions: int = 0, log_at_us: int | None = None
) -> uuid.UUID:
    """A game started at ``started``, with ``actions`` actions sent 1 second apart, and one
    log row at ``log_at_us`` if given."""
    seated = [Player(player_for(conn, f"{uuid.uuid4()}@x.org", cohort_seed=1), False)
              for _ in range(6)]  # fmt: skip
    game = start_game(
        conn, Formed(tuple(seated), "solo", cohort_table=False), seed=1, server_commit="t",
        started_at=started,
    )  # fmt: skip
    for seq in range(actions):
        conn.execute(
            insert(db.actions).values(
                game_id=game, seq=seq, action={"type": "OpenWindow"}, cause_seat=0,
                received_us=seq * 1_000_000, sent_us=seq * 1_000_000,
            )
        )  # fmt: skip
    if log_at_us is not None:
        conn.execute(
            insert(db.server_log).values(
                game_id=game, after_seq=0, at_us=log_at_us, seat=0, type="connection",
                data={"state": "connected"},
            )
        )  # fmt: skip
    return game


def ending(conn: Connection, game: uuid.UUID) -> str | None:
    return conn.execute(
        select(db.game_endings.c.completion).where(db.game_endings.c.game_id == game)
    ).scalar_one_or_none()


# ---------------------------------------------------------------- writing an ending


def test_an_ending_is_written_when_the_log_is_whole(app: Engine) -> None:
    with app.begin() as conn:
        game = a_game(conn, started=datetime.now(UTC), actions=3)
        assert write_ending(conn, game, "finished", 3) == "finished"
        assert ending(conn, game) == "finished"
        assert write_ending(conn, game, "unfinished", 3) == "unfinished"  # a second: nothing
        assert ending(conn, game) == "finished"


@pytest.mark.parametrize(("stored", "played"), [(3, 4), (3, 2)])
def test_a_log_with_a_gap_or_extra_rows_is_abandoned(
    app: Engine, stored: int, played: int, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        game = a_game(conn, started=datetime.now(UTC), actions=stored)
        assert write_ending(conn, game, "finished", played) == "abandoned"
        assert ending(conn, game) == "abandoned"


def test_a_log_whose_numbers_skip_is_abandoned(app: Engine) -> None:
    with app.begin() as conn:
        game = a_game(conn, started=datetime.now(UTC), actions=2)
        conn.execute(
            insert(db.actions).values(
                game_id=game, seq=5, action={"type": "OpenWindow"}, cause_seat=0,
                received_us=9_000_000, sent_us=9_000_000,
            )
        )  # fmt: skip
        assert write_ending(conn, game, "finished", 3) == "abandoned"


def test_the_hub_says_when_a_gap_abandons_a_game(
    app: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    from fish_server.game import Game

    with app.begin() as conn:
        game_id = a_game(conn, started=datetime.now(UTC), actions=1)
    Hub(lambda: app, "t").write_ending(Game(game_id, 1, [uuid.uuid4()] * 6), "finished", 2)
    assert "its log has a gap" in capsys.readouterr().out


# ---------------------------------------------------------------- the sweep


def test_the_sweep_abandons_only_quiet_games_not_running_here(app: Engine) -> None:
    now = datetime.now(UTC)
    with app.begin() as conn:
        crashed = a_game(conn, started=now - timedelta(hours=1), actions=5)
        quiet_log = a_game(conn, started=now - timedelta(hours=1), log_at_us=60_000_000)
        live = a_game(conn, started=now - timedelta(hours=1), actions=2,
                      log_at_us=int((timedelta(hours=1) - timedelta(seconds=20)).total_seconds()
                                    * 1_000_000))  # fmt: skip
        new = a_game(conn, started=now - timedelta(seconds=30))
        here = a_game(conn, started=now - timedelta(hours=2))
        done = a_game(conn, started=now - timedelta(hours=2), actions=1)
        write_ending(conn, done, "finished", 1)
    with app.begin() as conn:
        abandoned = abandon_quiet(conn, running=[here])
    assert set(abandoned) == {crashed, quiet_log}
    with app.connect() as conn:
        assert [ending(conn, g) for g in (crashed, quiet_log, live, new, here, done)] == [
            "abandoned", "abandoned", None, None, None, "finished",
        ]  # fmt: skip
    with app.begin() as conn:
        assert abandon_quiet(conn, running=[here]) == []  # once only
        assert abandon_quiet(conn, running=[], quiet=timedelta(0)) != []
    assert timedelta(minutes=5) == QUIET


def test_the_hub_sweeps_around_its_own_games(app: Engine) -> None:
    with app.begin() as conn:
        old = a_game(conn, started=datetime.now(UTC) - timedelta(hours=1))
    assert Hub(lambda: app, "t").sweep() == [old]
