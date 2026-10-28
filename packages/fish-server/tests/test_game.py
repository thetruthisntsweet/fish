"""One game in progress (T3.1), on a fake clock: who is sent what after each change, pings and
round trips, handovers releasing their person, the stand-in bot, the end of the game, and the
rows handed to the database. Whole random games played through ``Game`` give rows that make a
corpus record that reads back."""

import uuid
from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.action_index import encode
from fish_rules.cards import SEATS
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase
from fish_server.game import (
    PING_US,
    STAND_IN_DELAY_US,
    Acted,
    Connected,
    Disconnected,
    End,
    Game,
    Malformed,
    Ponged,
    Pressed,
    Release,
    Send,
)
from fish_server.protocol import Ping, Rejected, Update
from fish_server.table import RECONNECT_US, SECOND_US, TURN_US

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games: a fortieth of the profile's examples (10 in dev, 25 in CI, 1,250 nightly)."""


def new_game(seed: int = 1) -> Game:
    game = Game(uuid.uuid4(), seed, [uuid.uuid4() for _ in SEATS])
    for seat in SEATS:
        game.handle(Connected(seat), 0)
    return game


def sends[M](outs: Sequence[object], kind: type[M]) -> dict[int, M]:
    return {o.seat: o.message for o in outs if isinstance(o, Send) and isinstance(o.message, kind)}


def current(game: Game) -> int:
    seat = game.table.state.current
    assert seat is not None
    return seat


# ---------------------------------------------------------------- updates


def test_connecting_shows_the_seat_its_update() -> None:
    game = Game(uuid.uuid4(), 1, [uuid.uuid4() for _ in SEATS])
    outs = game.handle(Connected(2), 0)
    assert list(sends(outs, Update)) == [2]
    assert game.handle(Connected(2), 1) == []  # already connected


def test_every_connected_person_is_sent_every_change() -> None:
    game = new_game()
    game.handle(Disconnected(5), 10)
    seat = current(game)
    index = encode(game.table.actions(seat)[0])
    outs = game.handle(Acted(seat, index), 20)
    updates = sends(outs, Update)
    assert set(updates) == set(SEATS) - {5}
    assert all(u.view.seat == s for s, u in updates.items())


def test_a_rejected_input_is_answered_with_why_and_the_state() -> None:
    game = new_game()
    outs = game.handle(Pressed(0, 9 - 9, 50), 10)  # seen an event that never happened
    assert sends(outs, Rejected) == {
        0: Rejected(type="rejected", reason="malformed", discarded=False)
    }
    assert list(sends(outs, Update)) == [0]  # nothing changed, so only seat 0
    outs = game.handle(Malformed(3, "{"), 11)
    assert sends(outs, Rejected)[3].reason == "malformed"
    assert game.table.log[-1]["input"] == "{"


def test_a_press_is_shown_to_everyone() -> None:
    game = new_game()
    outs = game.handle(Pressed(4, 0, None), 10)
    assert set(sends(outs, Update)) == set(SEATS)
    assert game.table.state.phase is Phase.WINDOW


# ---------------------------------------------------------------- pings (R.8.7)


def test_r8_7_people_are_pinged_on_connecting_and_every_5_seconds() -> None:
    game = new_game()
    assert game.next_wake() == 0
    pings = sends(game.wake(0), Ping)
    assert set(pings) == set(SEATS)
    nonce = pings[2].nonce
    game.handle(Ponged(2, nonce), 38_000)
    game.handle(Ponged(2, nonce), 39_000)  # answered once only
    game.handle(Ponged(3, pings[4].nonce), 40_000)  # not seat 3's
    assert [(r["seat"], r["rtt_us"]) for r in game.table.log if r["type"] == "rtt"] == [(2, 38_000)]
    assert game.next_wake() == PING_US
    assert set(sends(game.wake(PING_US), Ping)) == set(SEATS)


def test_r8_7_a_reconnection_is_pinged_at_once() -> None:
    game = new_game()
    game.wake(0)
    game.handle(Disconnected(1), SECOND_US)
    game.handle(Connected(1), 2 * SECOND_US)
    assert list(sends(game.wake(2 * SECOND_US), Ping)) == [1]


# ---------------------------------------------------------------- handovers and the stand-in


def test_r8_4_a_handover_releases_its_person_and_a_bot_plays_on() -> None:
    game = new_game()
    seat = current(game)
    player = game.seats[seat]
    assert game.seat_of(player) == seat
    outs = game.wake(TURN_US)
    assert Release(seat) in outs
    assert sends(outs, Update)[seat].bots == [seat]  # told, once
    assert game.seat_of(player) is None
    assert game.seat_of(uuid.uuid4()) is None
    assert game.next_wake() == TURN_US + STAND_IN_DELAY_US - TURN_US + TURN_US
    events = len(game.table.entries)
    game.wake(TURN_US + STAND_IN_DELAY_US)
    assert len(game.table.entries) == events + 1  # the stand-in asked
    assert game.table.entries[-1].cause == {"seat": seat}


def test_r8_4_a_person_who_stays_away_is_released() -> None:
    game = new_game()
    seat = next(s for s in SEATS if s != current(game))
    game.handle(Disconnected(seat), SECOND_US)
    outs = game.wake(SECOND_US + RECONNECT_US)
    assert Release(seat) in outs
    assert seat not in sends(outs, Update)  # away: nothing to send to


def test_the_stand_in_waits_and_never_acts_on_a_changed_game() -> None:
    game = new_game()
    seat = current(game)
    game.wake(TURN_US)  # handed over; the stand-in will act in 2 seconds
    game.handle(Pressed((seat + 1) % 6, game.table.state.sets_in_play()[0], None), TURN_US + 1)
    game.wake(TURN_US + STAND_IN_DELAY_US)  # a window is open: the stand-in may not act
    assert game.table.entries[-1].cause.get("seat") != seat


# ---------------------------------------------------------------- the end and the rows


def play(rng: SplitMix64, game: Game, steps: int) -> list[object]:
    """Random inputs from the people, the clock moving on, until the game ends."""
    outs: list[object] = []
    now = 0
    for _ in range(steps):
        if game.ended:
            break
        now += rng.below(3 * SECOND_US)
        if (due := game.next_wake()) is not None and due <= now:
            outs += game.wake(now)
        seat = rng.choice(SEATS)
        if rng.below(10) == 0 and game.table.pressable(seat):
            seen = game.table.state.events - 1 if game.table.state.events else None
            outs += game.handle(Pressed(seat, rng.choice(game.table.pressable(seat)), seen), now)
        elif acting := [s for s in game.table.people if game.table.actions(s)]:
            seat = rng.choice(acting)
            index = encode(rng.choice(game.table.actions(seat)))
            outs += game.handle(Acted(seat, index), now)
        if rng.below(30) == 0:
            outs += game.handle(Disconnected(rng.choice(SEATS)), now)
        if rng.below(10) == 0:
            outs += game.handle(Connected(rng.choice(SEATS)), now)
        game.table.sent(now)
    while not game.ended and (due := game.next_wake()) is not None:  # bots finish it
        outs += game.wake(max(now, due))
        now = max(now, due)
        game.table.sent(now)
    return outs


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_whole_games_end_and_their_rows_are_the_log(game_seed: int, policy_seed: int) -> None:
    game = Game(uuid.uuid4(), game_seed, [uuid.uuid4() for _ in SEATS])
    outs = play(SplitMix64(policy_seed), game, 3_000)
    assert game.ended
    assert [o for o in outs if isinstance(o, End)] == [End(str(game.table.state.outcome))]
    assert game.next_wake() is None
    actions, log = game.rows()
    assert [a["seq"] for a in actions] == list(range(len(game.table.entries)))
    assert len(log) == len(game.table.log)
    assert game.rows() == ([], [])  # handed over once
    for row, entry in zip(actions, game.table.entries, strict=True):
        assert (row["received_us"], row["sent_us"]) == (entry.received_us, entry.sent_us)
        assert row["game_id"] == game.game_id


def test_actions_are_handed_over_only_once_sent() -> None:
    game = new_game()
    game.handle(Pressed(4, 0, None), 10)
    actions, log = game.rows()
    assert actions == []
    assert [r["type"] for r in log] == ["connection"] * 6
    game.table.sent(20)
    actions, _ = game.rows()
    assert [(a["seq"], a["cause_seat"], a["sent_us"]) for a in actions] == [
        (0, 4, 20),
        (1, 4, 20),
    ]
    assert actions[0]["action"] == {"type": "OpenWindow"}
