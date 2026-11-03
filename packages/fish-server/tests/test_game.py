"""One game in progress (T3.1), on a fake clock: who is sent what after each change, pings and
round trips, handovers releasing their person, B1 taking over their seat and its waits (R.8.8),
the end of the game, and the
rows handed to the database. Whole random games played through ``Game`` give rows that make a
corpus record that reads back."""

import dataclasses
import uuid
from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

from fish_agents.memory import MemorySetting
from fish_rules.action_index import encode
from fish_rules.cards import SEATS, set_cards
from fish_rules.corpus import read_corpus_record
from fish_rules.events import Ask, CallEvent, Declare, OpenWindow
from fish_rules.rng import SplitMix64
from fish_rules.state import CallSource, Phase
from fish_server.bots import BOT_DELAY_MAX_US, BOT_DELAY_MIN_US, DelayStreams
from fish_server.game import (
    BOT,
    PING_US,
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
from fish_server.table import RECONNECT_US, SECOND_US, TURN_US, Controller

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


# ---------------------------------------------------------------- handovers and B1


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
    due = game.next_wake()
    assert due is not None
    wait = due - TURN_US
    assert BOT_DELAY_MIN_US <= wait <= BOT_DELAY_MAX_US  # R.8.8
    assert wait == DelayStreams(1).delay(seat, game.table.state.events)  # from the seed
    events = len(game.table.entries)
    game.wake(due - 1)
    assert len(game.table.entries) == events  # not yet
    game.wake(due)
    assert len(game.table.entries) == events + 1  # the bot asked
    assert game.table.entries[-1].cause == {"seat": seat}
    waited = [row for row in game.table.log if row["type"] == "bot_delay"]
    assert waited == [
        {"type": "bot_delay", "after": events, "at_us": due, "seat": seat, "delay_us": wait,
         "dropped": False}
    ]  # fmt: skip


def test_r8_4_a_person_who_stays_away_is_released() -> None:
    game = new_game()
    seat = next(s for s in SEATS if s != current(game))
    game.handle(Disconnected(seat), SECOND_US)
    outs = game.wake(SECOND_US + RECONNECT_US)
    assert Release(seat) in outs
    assert seat not in sends(outs, Update)  # away: nothing to send to


def test_the_bot_waits_and_never_acts_on_a_changed_game() -> None:
    game = new_game()
    seat = current(game)
    game.wake(TURN_US)  # handed over; the bot will act after its wait
    due = game.next_wake()
    assert due is not None
    pressed = (seat + 1) % 6
    game.handle(Pressed(pressed, game.table.state.sets_in_play()[0], None), TURN_US + 1)
    dropped = [row for row in game.table.log if row["type"] == "bot_delay"]
    assert [(row["seat"], row["dropped"], row["at_us"]) for row in dropped] == [
        (seat, True, TURN_US + 1)  # the game moved on: the decision is dropped (R.8.8)
    ]
    game.wake(due)  # a window is open: the bot may not act
    assert game.table.entries[-1].cause.get("seat") != seat


def test_b1_remembering_8_events_takes_the_seat_and_is_recorded_so() -> None:
    game = new_game()
    seat = current(game)
    game.wake(TURN_US)
    (handover,) = [row for row in game.table.log if row["type"] == "handover"]
    assert (handover["agent"], handover["memory"], handover["k"]) == ("b1-v1", "last-k", 8)
    assert Controller("b1-v1", MemorySetting.last_k(8)) == BOT
    memory = game._bot.memory(seat)  # pyright: ignore[reportPrivateUsage]
    assert memory.view.seat == seat  # shown its seat's view from the moment it took it


def test_on_its_turn_b1_asks_as_the_website_allows_and_remembers_what_follows() -> None:
    game = new_game(seed=3)
    seat = current(game)
    game.wake(TURN_US)
    now = TURN_US
    asked = 0
    while asked < 3 and (due := game.next_wake()) is not None and due < 4 * TURN_US:
        before = len(game.table.entries)
        now = max(now, due)
        game.wake(now)
        for entry in game.table.entries[before:]:
            if entry.cause == {"seat": seat}:
                assert isinstance(entry.action, Ask)  # on a turn, only asks (R.4.3)
                asked += 1
    assert asked > 0
    memory = game._bot.memory(seat)  # pyright: ignore[reportPrivateUsage]
    assert 0 < len(memory.events) <= 8


def holding_a_whole_set(seed: int = 1) -> tuple[Game, int]:
    """A game whose current player holds all of set 0, so B1 can prove that call, and is
    about to be handed over for letting the turn timer run out."""
    game = new_game(seed)
    seat = current(game)
    state = game.table.state
    whole = set(set_cards(0))
    rest = [c for hand in state.hands for c in hand if c not in whole]
    hand = sorted(whole | set(rest[:3]))
    rest = rest[3:]
    hands = []
    for s in SEATS:
        if s == seat:
            hands.append(tuple(hand))
        else:
            hands.append(tuple(sorted(rest[:9])))
            rest = rest[9:]
    game.table.state = dataclasses.replace(state, hands=tuple(hands))
    return game, seat


def test_r8_8_a_bot_that_can_prove_a_call_presses_after_its_wait_and_makes_it() -> None:
    game, seat = holding_a_whole_set()
    game.wake(TURN_US)  # handed over: it decides at once
    due = game.next_wake()
    assert due is not None
    while not any(isinstance(e.action, Declare) for e in game.table.entries):
        due = game.next_wake()
        assert due is not None
        game.wake(due)
    declared = next(e for e in game.table.entries if isinstance(e.action, Declare))
    assert declared.action == Declare(seat, 0)
    waits = [r for r in game.table.log if r["type"] == "bot_delay" and not r["dropped"]]
    assert any(r["at_us"] == declared.received_us for r in waits)  # it waited first
    while not any(isinstance(r, CallEvent) for e in game.table.entries for r in e.records):
        due = game.next_wake()
        assert due is not None
        game.wake(due)
    (call,) = [r for e in game.table.entries for r in e.records if isinstance(r, CallEvent)]
    assert (call.caller, call.set_id, call.correct) == (seat, 0, True)


def test_r8_8_a_bot_does_not_declare_in_a_window_someone_else_opened() -> None:
    game, seat = holding_a_whole_set()
    game.wake(TURN_US)
    other = next(s for s in SEATS if s != seat)
    game.handle(Pressed(other, 1, None), TURN_US + 1)  # a person presses first
    for _ in range(3):
        if (due := game.next_wake()) is not None and due < TURN_US + 5 * SECOND_US:
            game.wake(due)
    assert Declare(seat, 0) not in [e.action for e in game.table.entries]
    dropped = [r for r in game.table.log if r["type"] == "bot_delay" and r["dropped"]]
    assert any(r["seat"] == seat for r in dropped)


def test_a_game_whose_people_have_all_gone_ends_abandoned_at_once() -> None:
    game = Game(uuid.uuid4(), 1, [uuid.uuid4() for _ in SEATS])
    game.handle(Connected(5), 1)  # one person comes; the other five never do
    outs = game.wake(RECONNECT_US + 1)  # five handed over; one person is still there
    assert not game.ended
    assert all(not isinstance(o, End) for o in outs)
    game.handle(Disconnected(5), RECONNECT_US + 2)
    actions = len(game.table.entries)
    outs = game.wake(2 * RECONNECT_US + 2)  # the last person gone: nobody to play with
    assert End("abandoned") in outs
    assert game.ended
    assert game.next_wake() is None  # no bot waits on, and no pings
    assert game.table.state.outcome is None  # the rules did not end it
    assert game.wake(3 * RECONNECT_US) == []
    assert len(game.table.entries) == actions


def test_the_same_seed_and_inputs_give_the_same_bot_play() -> None:
    first = Game(uuid.uuid4(), 9, [uuid.uuid4() for _ in SEATS])
    second = Game(uuid.uuid4(), 9, [uuid.uuid4() for _ in SEATS])
    play(SplitMix64(4), first, 3_000)
    play(SplitMix64(4), second, 3_000)
    assert [e.action for e in first.table.entries] == [e.action for e in second.table.entries]
    assert any(row["type"] == "handover" for row in first.table.log)


# ---------------------------------------------------------------- the end and the rows


def play(rng: SplitMix64, game: Game, steps: int) -> list[object]:
    """Random inputs from the people, the clock moving on, until the game ends: presses and
    actions only from seats people hold, as the hub sees to; the bots do the rest."""
    outs: list[object] = []
    now = 0
    for _ in range(steps):
        if game.ended:
            break
        now += rng.below(3 * SECOND_US)
        if (due := game.next_wake()) is not None and due <= now:
            outs += game.wake(now)
        seat = rng.choice(SEATS)
        if rng.below(10) == 0 and seat in game.table.people and game.table.pressable(seat):
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
    outcome = game.table.state.outcome
    ending = End(str(outcome)) if outcome is not None else End("abandoned")
    assert [o for o in outs if isinstance(o, End)] == [ending]
    assert (outcome is None) == (not game.table.people)  # abandoned only when nobody is left
    assert game.next_wake() is None
    actions, log = game.rows()
    assert [a["seq"] for a in actions] == list(range(len(game.table.entries)))
    assert len(log) == len(game.table.log)
    assert game.rows() == ([], [])  # handed over once
    for row, entry in zip(actions, game.table.entries, strict=True):
        assert (row["received_us"], row["sent_us"]) == (entry.received_us, entry.sent_us)
        assert row["game_id"] == game.game_id
    check_bot_waits(game)


def check_bot_waits(game: Game) -> None:
    """R.8.8: each action a bot took came straight after a wait of 1.5 to 4 seconds that was
    not dropped, and every wait is recorded for a bot's seat; the game reads back as a corpus
    record."""
    table = game.table
    waits = [row for row in table.log if row["type"] == "bot_delay"]
    bot_from = {row["seat"]: row["after"] for row in table.log if row["type"] == "handover"}
    for row in waits:
        assert row["seat"] in bot_from
        assert BOT_DELAY_MIN_US <= int(str(row["delay_us"])) <= BOT_DELAY_MAX_US
    for seq, entry in enumerate(table.entries):
        seat = entry.cause.get("seat")
        start = bot_from.get(seat)
        if start is None or seq < int(str(start)):
            continue  # a person's action, or a timer's
        if isinstance(entry.action, Declare) and seq and table.entries[seq - 1].action == OPEN:
            continue  # the second half of a press: its wait came before the OpenWindow
        taken = [r for r in waits if r["after"] == seq and r["seat"] == seat and not r["dropped"]]
        assert [r["at_us"] for r in taken] == [entry.received_us], (seq, seat)
    for seq, entry in enumerate(table.entries):
        for record in entry.records:
            if not isinstance(record, CallEvent) or record.source is CallSource.RUNOUT:
                continue
            start = bot_from.get(record.caller)
            declared = max(
                (n for n in range(seq) if table.entries[n].action == Declare(record.caller,
                                                                              record.set_id)),
                default=-1,
            )  # fmt: skip
            if start is not None and declared >= int(str(start)):
                assert record.correct, record  # a bot presses only what it can prove (D85)
    completion = "abandoned" if table.state.outcome is None else str(table.state.outcome)
    seats = [person(s) if s in table.seated else bot() for s in SEATS]
    record = table.record(game=GAME | {"completion": completion}, seats=seats)
    read_corpus_record(record)


OPEN = OpenWindow()
GAME = {"id": "g-test", "month": "2026-12", "matchmaking": "solo", "cohort_table": False,
        "server_commit": "test", "protocol_version": 1}  # fmt: skip
CONSENT = {"version": "v1.0", "us_resident_adult": True, "agrees": True,
           "no_outside_communication": True}  # fmt: skip


def person(seat: int) -> dict[str, object]:
    return {"person": f"p{seat}", "cohort": False, "agent": None, "memory": "human", "k": None,
            "note": "no", "consent": CONSENT}  # fmt: skip


def bot() -> dict[str, object]:
    return {"person": None, "cohort": None, "agent": "b1-v1", "memory": "last-k", "k": 8,
            "note": None, "consent": None}  # fmt: skip


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
