"""Matchmaking (T3.1): the solo queue matches cohort players only with each other, rooms seat
the six who join them, a player waits in one place at a time, and seats are drawn at random.
Random sequences of joins and leaves keep every promise. Writing a new table is checked
against the database (skipped without FISH_TEST_DATABASE_URL)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, create_engine, insert, pool, select

from fish_rules.codec import ACTION_ENCODING
from fish_rules.state import STATE_ENCODING
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.games import load_player, new_seed, start_game
from fish_server.lobby import Formed, Lobby, NotNowError, Player, Waiting
from fish_server.protocol import PROTOCOL_VERSION, ROOM_CODE_PATTERN, parse_client_message
from fish_server.settings import COMMIT_VAR, RENDER_COMMIT_VAR, database_url, server_commit


def people(n: int, *, cohort: bool = False) -> list[Player]:
    return [Player(uuid.uuid4(), cohort) for _ in range(n)]


def keep_order(players: list[Player]) -> None:
    """A shuffle that leaves the seats in join order, so tests can name them."""


# ---------------------------------------------------------------- the solo queue


def test_six_in_the_queue_form_a_table() -> None:
    lobby, six = Lobby(keep_order), people(6)
    for n, player in enumerate(six[:5], start=1):
        assert lobby.join_queue(player) is None
        assert lobby.waiting(player) == Waiting("solo", None, n)
    table = lobby.join_queue(six[5])
    assert table == Formed(tuple(six), "solo", cohort_table=False)
    assert all(lobby.waiting(p) is None for p in six)
    assert lobby.seated == {p.id for p in six}


def test_cohort_players_are_matched_only_with_each_other() -> None:
    lobby = Lobby(keep_order)
    cohort, others = people(6, cohort=True), people(5)
    for player in others:
        lobby.join_queue(player)
    for player in cohort[:5]:
        assert lobby.join_queue(player) is None  # ten waiting, but in two queues
    table = lobby.join_queue(cohort[5])
    assert table is not None
    assert table.cohort_table
    assert all(p.cohort for p in table.seats)
    assert lobby.waiting(others[0]) == Waiting("solo", None, 5)


def test_the_longest_waiting_six_are_seated() -> None:
    lobby, waiting = Lobby(keep_order), people(6)
    for player in waiting[:5]:
        lobby.join_queue(player)
    lobby.leave(waiting[0])
    late = people(2)
    assert lobby.join_queue(waiting[5]) is None
    table = lobby.join_queue(late[0])
    assert table is not None
    assert table.seats == (*waiting[1:], late[0])


def test_seats_are_drawn_at_random() -> None:
    orders = set()
    for _ in range(30):
        lobby, six = Lobby(), people(6)
        tables = [lobby.join_queue(p) for p in six]
        table = tables[-1]
        assert table is not None
        assert set(table.seats) == set(six)
        orders.add(tuple(six.index(p) for p in table.seats))
    assert len(orders) > 1


# ---------------------------------------------------------------- rooms


def test_a_room_seats_the_six_who_join_it_cohort_or_not() -> None:
    lobby = Lobby(keep_order, new_code=lambda: "ABC234")
    host, *friends = [*people(3, cohort=True), *people(3)]
    code = lobby.create_room(host)
    assert code == "ABC234"
    assert lobby.waiting(host) == Waiting("group", code, 1)
    for n, friend in enumerate(friends[:4], start=2):
        assert lobby.join_room(friend, code) is None
        assert lobby.waiting(friend) == Waiting("group", code, n)
    assert set(lobby.others(host)) == {host, *friends[:4]}
    table = lobby.join_room(friends[4], code)
    assert table == Formed((host, *friends), "group", cohort_table=False)
    with pytest.raises(NotNowError, match="no room"):
        lobby.join_room(people(1)[0], code)  # the room is now a table


def test_room_codes_are_new_and_readable() -> None:
    codes = iter(["AAAAAA", "AAAAAA", "BBBBBB"])
    lobby = Lobby(new_code=lambda: next(codes))
    assert lobby.create_room(people(1)[0]) == "AAAAAA"
    assert lobby.create_room(people(1)[0]) == "BBBBBB"  # AAAAAA is taken
    real = Lobby().create_room(people(1)[0])
    parse_client_message(f'{{"type": "join_room", "code": "{real}"}}')  # matches the protocol
    assert ROOM_CODE_PATTERN.startswith("^")


def test_leaving_a_room() -> None:
    lobby = Lobby(keep_order)
    host, guest = people(2)
    code = lobby.create_room(host)
    lobby.join_room(guest, code)
    assert lobby.leave(host) == (guest,)
    assert lobby.waiting(guest) == Waiting("group", code, 1)
    assert lobby.leave(guest) == ()
    with pytest.raises(NotNowError):
        lobby.join_room(host, code)  # an empty room is gone


# ---------------------------------------------------------------- one place at a time


def test_a_player_waits_in_one_place_at_a_time() -> None:
    lobby = Lobby(keep_order)
    player = people(1)[0]
    lobby.join_queue(player)
    with pytest.raises(NotNowError, match="already waiting"):
        lobby.join_queue(player)
    with pytest.raises(NotNowError, match="already waiting"):
        lobby.create_room(player)
    assert lobby.others(player) == (player,)
    assert lobby.leave(player) == ()
    assert lobby.leave(player) == ()  # not waiting: nothing changes
    assert lobby.others(player) == ()
    lobby.create_room(player)  # now free


def test_a_seated_player_waits_again_only_when_the_table_ends() -> None:
    lobby, six = Lobby(keep_order), people(6)
    for player in six:
        lobby.join_queue(player)
    with pytest.raises(NotNowError, match="at a table"):
        lobby.join_queue(six[0])
    lobby.left_table(six)
    assert lobby.join_queue(six[0]) is None


@settings(deadline=None)
@given(st.lists(st.tuples(st.integers(0, 3), st.integers(0, 13)), max_size=300))
def test_random_joins_and_leaves_keep_every_promise(moves: list[tuple[int, int]]) -> None:
    lobby = Lobby()
    pool_ = [*people(7, cohort=True), *people(7)]
    seen_tables: list[Formed] = []
    for kind, who in moves:
        player = pool_[who]
        try:
            match kind:
                case 0:
                    table = lobby.join_queue(player)
                case 1:
                    table = (
                        lobby.join_room(player, rooms[0]) if (rooms := lobby_codes(lobby)) else None
                    )
                case 2:
                    lobby.create_room(player)
                    table = None
                case _:
                    lobby.leave(player)
                    table = None
        except NotNowError:
            table = None
        if table is not None:
            seen_tables.append(table)
            assert len({p.id for p in table.seats}) == 6
            if table.matchmaking == "solo":
                assert table.cohort_table == all(p.cohort for p in table.seats)
                assert len({p.cohort for p in table.seats}) == 1
            else:
                assert not table.cohort_table
            if len(seen_tables) % 2:
                lobby.left_table(table.seats)
        for p in pool_:  # nobody waits in two places, or waits while seated
            where = lobby.waiting(p)
            assert where is None or p.id not in lobby.seated
            if where is not None:
                assert p in lobby.others(p)
                assert where.people == len(lobby.others(p))


def lobby_codes(lobby: Lobby) -> list[str]:
    return sorted(lobby._rooms)  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------- writing a new table


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def signed_up(app: Engine, n: int, *, cohort: bool) -> list[Player]:
    players = people(n, cohort=cohort)
    with app.begin() as conn:
        for player in players:
            number = conn.execute(select(db.signup_numbers.next_value())).scalar_one()
            conn.execute(
                insert(db.players).values(
                    player_id=player.id, signup_number=number, cohort=player.cohort
                )
            )
    return players


def test_a_new_table_is_written_before_its_first_action(app: Engine) -> None:
    six = signed_up(app, 6, cohort=True)
    table = Formed(tuple(six), "solo", cohort_table=True)
    started = datetime(2026, 12, 13, 20, 0, tzinfo=UTC)
    seed = new_seed()
    with app.begin() as conn:
        game = start_game(conn, table, seed=seed, server_commit="abc1234", started_at=started)
    with app.connect() as conn:
        row = conn.execute(select(db.games).where(db.games.c.game_id == game)).one()
        seats = conn.execute(
            select(db.seats).where(db.seats.c.game_id == game).order_by(db.seats.c.seat)
        ).all()
        assert load_player(conn, six[2].id) == six[2]
    assert int(row.seed) == seed
    assert (row.ruleset, row.action_encoding, row.state_encoding) == (
        RULESET_VERSION,
        ACTION_ENCODING,
        STATE_ENCODING,
    )
    assert (row.server_commit, row.protocol_version) == ("abc1234", PROTOCOL_VERSION)
    assert (row.matchmaking, row.cohort_table, row.started_at) == ("solo", True, started)
    assert [(s.seat, s.player_id, s.agent, s.memory, s.k) for s in seats] == [
        (n, p.id, None, "human", None) for n, p in enumerate(six)
    ]


def test_each_person_s_seat_copies_their_latest_acceptance(app: Engine) -> None:
    """Consent Screen §3: the seat's flags are the person's latest acceptance when the game
    starts; a person with none gets none, and the game cannot enter the corpus."""
    six = signed_up(app, 6, cohort=False)
    confirmed = {"us_resident_adult": True, "agrees": True, "no_outside_communication": True}
    with app.begin() as conn:
        for player in six[:5]:
            conn.execute(
                insert(db.consents).values(player_id=player.id, version="v1.0", **confirmed)
            )
        conn.execute(insert(db.consents).values(player_id=six[0].id, version="v1.1", **confirmed))
        game = start_game(
            conn, Formed(tuple(six), "solo", cohort_table=False), seed=1, server_commit="t",
            started_at=datetime(2026, 12, 13, tzinfo=UTC),
        )  # fmt: skip
        flags = (
            conn.execute(select(db.seat_consents).where(db.seat_consents.c.game_id == game))
            .mappings()
            .all()
        )
    by_seat = {row["seat"]: row for row in flags}
    assert sorted(by_seat) == [0, 1, 2, 3, 4]  # the sixth person has not accepted
    assert by_seat[0]["version"] == "v1.1"
    assert all(by_seat[s]["player_id"] == six[s].id for s in by_seat)
    assert all(row["us_resident_adult"] and row["agrees"] for row in flags)


def test_seeds_are_64_bit_and_differ() -> None:
    seeds = {new_seed() for _ in range(50)}
    assert len(seeds) == 50
    assert all(0 <= s < 2**64 for s in seeds)


def test_the_commit_comes_from_the_settings_or_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(COMMIT_VAR, raising=False)
    monkeypatch.delenv(RENDER_COMMIT_VAR, raising=False)
    assert server_commit() == "dev"
    monkeypatch.setenv(RENDER_COMMIT_VAR, "f00d")
    assert server_commit() == "f00d"
    monkeypatch.setenv(COMMIT_VAR, "beef")
    assert server_commit() == "beef"
