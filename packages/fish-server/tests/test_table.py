"""The table: the engine under website mechanics (T3.1). Presses open 1-second windows, the
assignment and the after-call choice time out, stale presses, discarded actions and illegal
inputs are rejected and logged, and every timer runs on the server clock. A person who does
not act within 60 seconds, or reconnect within 30, is replaced by a bot. Over random games
with random inputs, connections and disconnections at random times, every game the table
plays is a corpus record that reads back."""

from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_agents.memory import NONE
from fish_rules.cards import SEATS, set_cards, set_of, team_of, team_seats
from fish_rules.corpus import read_corpus_record
from fish_rules.engine import legal_actions
from fish_rules.events import (
    Ask,
    AskEvent,
    Assign,
    AssignTimeout,
    Call,
    CallEvent,
    ChoiceTimeout,
    CloseWindow,
    Declare,
    OpenWindow,
    Pass,
)
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase
from fish_server.table import (
    ASSIGN_US,
    CHOICE_US,
    RECONNECT_US,
    SECOND_US,
    TURN_US,
    WINDOW_US,
    Accepted,
    Controller,
    Rejected,
    Table,
)

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games with every seat's inputs: a fortieth of the profile's examples (10 in dev, 25
in CI, 1,250 nightly)."""

GAME: Final = {
    "id": "g-test",
    "month": "2026-12",
    "matchmaking": "solo",
    "cohort_table": False,
    "server_commit": "test",
    "protocol_version": 1,
}
STAND_IN: Final = Controller("b0-v1", NONE)
"""The bot that takes over a seat in these tests (T3.5 supplies B1 for the website)."""


CONSENT: Final = {
    "version": "v1.0",
    "us_resident_adult": True,
    "agrees": True,
    "no_outside_communication": True,
}


def person(seat: int) -> dict[str, object]:
    return {"person": f"p{seat}", "cohort": False, "agent": None, "memory": "human", "k": None,
            "note": "no", "consent": CONSENT}  # fmt: skip


def bot(seat: int) -> dict[str, object]:
    return {"person": None, "cohort": None, "agent": "b0-v1", "memory": "none", "k": None,
            "note": None, "consent": None}  # fmt: skip


def new_table(seed: int, people: tuple[int, ...] = SEATS) -> Table:
    """A table whose people all connect at the deal."""
    table = Table(seed, people=people, replacement=STAND_IN)
    for seat in people:
        assert table.connect(seat, 0)
    return table


def record(table: Table) -> dict[str, object]:
    """The table's game as a corpus record, read back."""
    outcome = table.state.outcome
    completion = "abandoned" if outcome is None else str(outcome)
    seats = [person(s) if s in table.seated else bot(s) for s in SEATS]
    data = table.record(game=GAME | {"completion": completion}, seats=seats)
    read_corpus_record(data)
    return data


def rows(table: Table, kind: str) -> list[dict[str, object]]:
    return [row for row in table.log if row["type"] == kind]


def other_set(table: Table, not_this: int) -> int:
    return next(s for s in table.state.sets_in_play() if s != not_this)


def to_assignment(table: Table, seat: int = 2, at: int = 0) -> int:
    """Press for ``seat`` at ``at`` and let the window close; returns when it closed."""
    assert table.press(seat, table.state.sets_in_play()[0], None, at) == Accepted(2)
    table.advance(at + WINDOW_US)
    assert table.state.phase is Phase.ASSIGN
    return at + WINDOW_US


# ---------------------------------------------------------------- presses and windows (R.8.3)


def test_r8_3_a_press_opens_a_one_second_window_with_the_pressers_declaration() -> None:
    table = new_table(1)
    set_id = table.state.sets_in_play()[3]
    assert table.press(2, set_id, None, 500_000) == Accepted(2)
    assert [(e.action, e.cause, e.received_us) for e in table.entries] == [
        (OpenWindow(), {"seat": 2}, 500_000),
        (Declare(2, set_id), {"seat": 2}, 500_000),
    ]
    assert table.deadline() == 500_000 + WINDOW_US
    assert table.pressable(2) == ()  # one declaration per window
    assert table.press(2, set_id, None, 600_000) == Rejected("illegal")
    assert table.press(4, other_set(table, set_id), None, 900_000) == Accepted(1)
    assert table.entries[-1].action == Declare(4, other_set(table, set_id))
    assert table.advance(1_499_999) == 0
    assert table.advance(1_500_000) == 1
    assert table.entries[-1].action == CloseWindow()
    assert table.entries[-1].cause == {"timer": "window"}
    assert table.state.phase is Phase.ASSIGN


def test_r8_3_players_see_that_a_window_opened_but_not_who_declared() -> None:
    table = new_table(1)
    set_id = table.state.sets_in_play()[2]
    table.press(4, set_id, None, 0)
    for seat in SEATS:
        view = table.view(seat)
        assert view.window_open
        assert view.own_declaration == (set_id if seat == 4 else None)


def test_r8_3_an_action_sent_while_a_window_is_open_is_discarded() -> None:
    table = new_table(1)
    current = table.state.current
    assert current is not None
    ask = table.actions(current)[0]
    table.press(4, table.state.sets_in_play()[0], None, 0)
    assert table.actions(current) == ()
    assert table.act(current, ask, 10) == Rejected("illegal", discarded=True)
    assert table.log[-1] == {
        "type": "rejected",
        "after": 2,
        "at_us": 10,
        "seat": current,
        "input": {"type": "Ask", "seat": ask.seat, "target": ask.target, "card": ask.card},  # pyright: ignore[reportAttributeAccessIssue]
        "reason": "illegal",
    }


def test_r8_3_presses_during_an_assignment_or_a_choice_are_rejected() -> None:
    table = new_table(1)
    closed = to_assignment(table)
    assert table.pressable(0) == ()
    assert table.press(0, table.state.sets_in_play()[0], None, closed + 1) == Rejected("illegal")
    table.advance(closed + ASSIGN_US)
    assert table.state.phase in (Phase.CHOOSE, Phase.VOTE)
    assert table.press(3, table.state.sets_in_play()[0], 0, closed + ASSIGN_US + 1) == Rejected(
        "illegal"
    )
    assert [row["reason"] for row in rows(table, "rejected")] == ["illegal", "illegal"]


def test_r4_3_on_a_turn_a_call_starts_with_a_press() -> None:
    table = new_table(1)
    current = table.state.current
    assert current is not None
    assert all(isinstance(a, Ask) for a in table.actions(current))
    call = Call(current, table.state.sets_in_play()[0])
    assert call in legal_actions(table.state, current)  # the engine allows it, the website not
    assert table.act(current, call, 0) == Rejected("illegal")


# ---------------------------------------------------------------- timers (R.4.3, R.5.2, R.8.5)


def test_r4_3_the_caller_has_30_seconds_to_assign() -> None:
    table = new_table(1)
    closed = to_assignment(table)
    assert table.deadline() == closed + ASSIGN_US
    assert table.advance(closed + ASSIGN_US - 1) == 0
    assert table.advance(closed + ASSIGN_US) == 1
    entry = table.entries[-1]
    assert (entry.action, entry.cause, entry.received_us) == (
        AssignTimeout(),
        {"timer": "assignment"},
        closed + ASSIGN_US,
    )
    (call,) = [r for r in entry.records if isinstance(r, CallEvent)]
    assert call.assignment is None
    assert not call.correct


def test_r5_2_the_after_call_choice_has_15_seconds() -> None:
    table = new_table(1)
    closed = to_assignment(table)
    table.advance(closed + ASSIGN_US)
    assert table.state.phase in (Phase.CHOOSE, Phase.VOTE)
    assert table.deadline() == closed + ASSIGN_US + CHOICE_US
    assert table.advance(closed + ASSIGN_US + CHOICE_US) == 1
    entry = table.entries[-1]
    assert (entry.action, entry.cause) == (ChoiceTimeout(), {"timer": "choice"})
    assert table.state.phase is Phase.TURN
    assert table.deadline() == table.turn_deadline() == closed + ASSIGN_US + CHOICE_US + TURN_US


def test_r8_5_timers_run_on_the_server_clock_however_late_they_are_checked() -> None:
    """A timer's action is received at its deadline on the server clock, not when the table
    was next asked; an input that arrives later first lets every timer due by then fire."""
    table = new_table(1)
    table.press(1, table.state.sets_in_play()[0], None, 7)
    late = 7 + WINDOW_US + ASSIGN_US + 3 * SECOND_US
    assert table.press(4, table.state.sets_in_play()[0], None, late) == Rejected("illegal")
    assert [(type(e.action), e.received_us) for e in table.entries[2:]] == [
        (CloseWindow, 7 + WINDOW_US),
        (AssignTimeout, 7 + WINDOW_US + ASSIGN_US),
    ]
    assert table.log[-1]["after"] == 4  # the press came after both timers


def test_an_assignment_in_time_stops_the_timer() -> None:
    table = new_table(1)
    closed = to_assignment(table)
    caller = table.state.call
    assert caller is not None
    assign = table.actions(caller.caller)[0]
    assert isinstance(assign, Assign)
    assert table.act(caller.caller, assign, closed + 2 * SECOND_US) == Accepted(1)
    assert table.entries[-1].cause == {"seat": caller.caller}
    assert table.state.phase is not Phase.ASSIGN


# ---------------------------------------------------------------- stale presses (R.8.7)


def successful_ask() -> tuple[Table, Ask]:
    """A table whose first action was a successful ask, applied at time 0."""
    for seed in range(100):
        table = new_table(seed)
        current = table.state.current
        assert current is not None
        for ask in table.actions(current):
            assert isinstance(ask, Ask)
            if table.state.holder(ask.card) == ask.target:
                assert table.act(current, ask, 0) == Accepted(1)
                return table, ask
    raise AssertionError("no seed in 100 has a successful first ask")  # pragma: no cover


def test_r8_7_a_press_is_rejected_if_an_unseen_event_moved_a_card_of_its_set() -> None:
    table, ask = successful_ask()
    moved = set_of(ask.card)
    untouched = other_set(table, moved)
    assert table.press(3, moved, None, 5) == Rejected("stale")
    assert table.log[-1]["reason"] == "stale"
    assert table.press(3, untouched, None, 6) == Accepted(2)  # taken against the current state
    assert table.press(4, moved, 0, 7) == Accepted(1)  # seat 4 had seen the ask


def test_r8_7_a_failed_ask_moves_nothing() -> None:
    for seed in range(100):
        table = new_table(seed)
        current = table.state.current
        assert current is not None
        ask = next(
            (a for a in table.actions(current) if table.state.holder(a.card) != a.target),  # pyright: ignore[reportAttributeAccessIssue]
            None,
        )
        if ask is not None:
            table.act(current, ask, 0)
            assert isinstance(table.entries[0].records[0], AskEvent)
            assert table.press(0, set_of(ask.card), None, 1) == Accepted(2)  # pyright: ignore[reportAttributeAccessIssue]
            return
    raise AssertionError("no seed in 100 has a failed first ask")  # pragma: no cover


def test_r8_7_a_press_is_rejected_if_a_call_it_had_not_seen_scored_its_set() -> None:
    table = new_table(1)
    closed = to_assignment(table, seat=1)
    called = table.state.call
    assert called is not None
    table.advance(closed + ASSIGN_US + CHOICE_US)  # the call times out, the choice too
    assert table.state.phase is Phase.TURN
    assert table.press(5, called.set_id, None, closed + ASSIGN_US + CHOICE_US) == Rejected("stale")
    seen = table.state.events - 2  # the call, before the after-call choice
    assert table.press(5, called.set_id, seen, closed + ASSIGN_US + CHOICE_US) == Rejected(
        "illegal"
    )  # it had seen the set scored: not stale, but no longer in play


# ---------------------------------------------------------------- what is rejected (R.8.7)


def test_r8_7_illegal_actions_are_rejected_and_the_seat_acts_again() -> None:
    table = new_table(1)
    current = table.state.current
    assert current is not None
    other = next(s for s in SEATS if s != current)
    foreign = Ask(other, current, 0)
    assert table.act(other, foreign, 1) == Rejected("illegal")
    assert table.act(current, Pass(current), 2) == Rejected("illegal")  # nobody passes
    assert table.act(current, Declare(current, 0), 3) == Rejected("illegal")  # declare by pressing
    assert table.act(current, table.actions(current)[0], 4) == Accepted(1)
    assert [row["at_us"] for row in rows(table, "rejected")] == [1, 2, 3]


@pytest.mark.parametrize(
    ("set_id", "seen"),
    [(9, None), (-1, None), (True, None), (0, 0), (0, -1), (0, True)],
)
def test_a_press_that_cannot_be_read_is_malformed(set_id: int, seen: int | None) -> None:
    table = new_table(1)
    assert table.press(0, set_id, seen, 0) == Rejected("malformed")


def test_control_actions_and_actions_for_another_seat_are_malformed() -> None:
    table = new_table(1)
    current = table.state.current
    assert current is not None
    other = next(s for s in SEATS if s != current)
    assert table.act(current, OpenWindow(), 0) == Rejected("malformed")
    assert table.act(other, table.actions(current)[0], 0) == Rejected("malformed")
    assert table.reject(3, "{not json", "malformed", 0) == Rejected("malformed")
    assert [row["reason"] for row in rows(table, "rejected")] == ["malformed"] * 3
    assert table.log[-1]["input"] == "{not json"


def test_inputs_after_the_game_are_rejected() -> None:
    table = play(SplitMix64(3), new_table(3), 5_000)
    if table.state.phase is Phase.OVER:
        assert table.press(0, 0, None, 10**12) == Rejected("illegal")
        assert table.actions(0) == ()


def test_the_table_refuses_misuse() -> None:
    table = new_table(1)
    table.advance(100)
    with pytest.raises(ValueError, match="time never goes back"):
        table.advance(99)
    with pytest.raises(ValueError, match="no seat"):
        table.reject(6, None, "malformed", 100)
    table.press(0, 0, None, 100)
    with pytest.raises(ValueError, match="every action must be sent"):
        table.record(game=GAME | {"completion": "abandoned"}, seats=[person(s) for s in SEATS])
    assert table.sent(150) == 2
    assert table.sent(160) == 0
    assert [e.sent_us for e in table.entries] == [150, 150]


# ---------------------------------------------------------------- the turn timer (R.8.4)


def handover(seat: int, reason: str, at: int, after: int = 0) -> dict[str, object]:
    return {"type": "handover", "after": after, "at_us": at, "seat": seat, "reason": reason,
            "agent": "b0-v1", "memory": "none", "k": None}  # fmt: skip


def first_player(table: Table) -> int:
    current = table.state.current
    assert current is not None
    return current


def test_r8_4_a_player_who_does_not_act_in_60_seconds_is_replaced_by_a_bot() -> None:
    table = new_table(1)
    current = first_player(table)
    assert table.turn_deadline() == TURN_US
    assert table.advance(TURN_US - 1) == 0
    assert table.advance(TURN_US) == 1
    assert rows(table, "handover") == [handover(current, "turn_timeout", TURN_US)]
    assert current not in table.people
    assert not table.connected(current)
    assert table.turn_deadline() is None  # a bot's turn is not timed
    assert table.act(current, table.actions(current)[0], TURN_US + 1) == Accepted(1)  # the bot
    assert not table.connect(current, TURN_US + 2)  # the person does not reclaim the seat
    assert not table.disconnect(current, TURN_US + 3)


def test_r8_4_every_new_turn_starts_a_fresh_60_seconds() -> None:
    table = new_table(1)
    current = first_player(table)
    table.act(current, table.actions(current)[0], 50 * SECOND_US)  # an ask: a new turn
    assert table.turn_deadline() == 50 * SECOND_US + TURN_US
    assert table.advance(TURN_US + 10 * SECOND_US) == 0


def test_r8_4_the_turn_timer_pauses_during_a_window_an_assignment_and_a_choice() -> None:
    table = new_table(1)
    closed = to_assignment(table, at=40 * SECOND_US)  # the turn had 20 seconds left
    assert table.turn_deadline() is None
    table.advance(closed + ASSIGN_US + CHOICE_US)  # 46 more seconds: no handover
    assert rows(table, "handover") == []
    assert table.turn_deadline() == closed + ASSIGN_US + CHOICE_US + TURN_US  # a new turn


# ---------------------------------------------------------------- connections (R.8.4)


def test_r8_4_a_player_who_disconnects_has_30_seconds_to_reconnect() -> None:
    seat = next(s for s in SEATS if s != first_player(new_table(1)))
    table = new_table(1, people=(seat,))  # bots elsewhere, so no turn timer runs
    assert table.disconnect(seat, 5 * SECOND_US)
    assert not table.disconnect(seat, 6 * SECOND_US)  # already gone
    assert table.connect(seat, 5 * SECOND_US + RECONNECT_US - 1)
    assert not table.connect(seat, 5 * SECOND_US + RECONNECT_US)  # already back
    assert table.disconnect(seat, 40 * SECOND_US)
    assert table.advance(40 * SECOND_US + RECONNECT_US) == 1
    assert [(r["state"], r["at_us"]) for r in rows(table, "connection")] == [
        ("connected", 0),
        ("disconnected", 5 * SECOND_US),
        ("reconnected", 5 * SECOND_US + RECONNECT_US - 1),
        ("disconnected", 40 * SECOND_US),
    ]
    assert rows(table, "handover") == [handover(seat, "disconnect", 40 * SECOND_US + RECONNECT_US)]
    assert not table.connect(seat, 80 * SECOND_US)


def test_r8_4_the_turn_timer_keeps_running_while_the_player_is_away() -> None:
    table = new_table(1)
    current = first_player(table)
    table.disconnect(current, 20 * SECOND_US)
    table.connect(current, 40 * SECOND_US)
    assert table.turn_deadline() == TURN_US
    table.advance(TURN_US)
    assert rows(table, "handover") == [handover(current, "turn_timeout", TURN_US)]


def test_r8_4_the_turn_timer_goes_first_when_both_run_out_at_once() -> None:
    table = new_table(1)
    current = first_player(table)
    table.disconnect(current, TURN_US - RECONNECT_US)
    table.advance(TURN_US)
    assert rows(table, "handover") == [handover(current, "turn_timeout", TURN_US)]


def test_r8_4_people_who_never_connect_are_handed_over_after_30_seconds() -> None:
    table = Table(1, people=SEATS, replacement=STAND_IN)
    assert table.connect(2, 1)
    assert table.advance(RECONNECT_US) == 5
    assert [r["seat"] for r in rows(table, "handover")] == [s for s in SEATS if s != 2]
    assert table.people == {2}
    assert rows(table, "connection")[0]["state"] == "connected"


def test_r8_7_round_trips_are_recorded_for_connected_people_only() -> None:
    table = new_table(1, people=(0, 1))
    assert table.round_trip(0, 41_000, 5 * SECOND_US)
    assert not table.round_trip(2, 41_000, 5 * SECOND_US)  # a bot's seat
    table.disconnect(1, 6 * SECOND_US)
    assert not table.round_trip(1, 41_000, 7 * SECOND_US)  # away
    assert not table.round_trip(0, -1, 8 * SECOND_US)
    assert rows(table, "rtt") == [
        {"type": "rtt", "after": 0, "at_us": 5 * SECOND_US, "seat": 0, "rtt_us": 41_000}
    ]
    record(table)


def test_seats_a_bot_holds_from_the_deal_have_no_timers() -> None:
    current = first_player(new_table(1))
    alone = next(s for s in SEATS if s != current)
    table = new_table(1, people=(alone,))
    assert table.turn_deadline() is None
    assert table.deadline() is None
    assert not table.connect(current, 1)
    record(table)


def test_nothing_is_handed_over_once_the_game_is_over() -> None:
    table = play(SplitMix64(3), new_table(3), 5_000)
    assert table.state.phase is Phase.OVER
    connected = [s for s in table.people if table.connected(s)]
    assert table.disconnect(connected[0], 10**12)
    count = len(table.log)
    assert table.advance(10**13) == 0
    assert len(table.log) == count
    assert table.deadline() is None


def test_people_are_one_or_more_seats() -> None:
    for people in ((), (6,)):
        with pytest.raises(ValueError, match="one or more seats"):
            Table(1, people=people, replacement=STAND_IN)


# ---------------------------------------------------------------- whole random games


def complete_sets(table: Table, seat: int) -> tuple[int, ...]:
    """Sets in play whose six cards ``seat``'s team holds (hidden state; a test may)."""
    mates = team_seats(team_of(seat))
    return tuple(
        s
        for s in table.state.sets_in_play()
        if all(table.state.holder(card) in mates for card in set_cards(s))
    )


def true_assignment(table: Table, caller: int) -> Assign:
    """The caller's assignment of every card to its true holder (hidden state; a test may)."""
    call = table.state.call
    assert call is not None
    holders = (table.state.holder(card) for card in set_cards(call.set_id))
    mates = team_seats(team_of(caller))
    return Assign(caller, tuple(h if h in mates else caller for h in holders))


def play(rng: SplitMix64, table: Table, steps: int, phases: set[Phase] | None = None) -> Table:
    """Random inputs from random seats at random times, legal or not, people connecting and
    disconnecting, and updates sent at random moments. Checks, as it goes, what the table
    promises about timers and rejections."""
    now = 0
    for _ in range(steps):
        if table.state.phase is Phase.OVER:
            break
        now += rng.below(3 * SECOND_US) if rng.below(6) else rng.below(40 * SECOND_US)
        due, entries, count = table.deadline(), len(table.entries), len(table.log)
        seat = rng.choice(SEATS)
        result = None
        match rng.below(14):
            case 0:
                sets = complete_sets(table, seat) if rng.below(2) else ()
                sets = sets or table.state.sets_in_play() or (0,)
                events = table.state.events
                seen = rng.choice((None, *range(max(0, events - 3), events)))
                result = table.press(seat, rng.choice(sets), seen, now)
            case n if n < 9 and (acting := [s for s in SEATS if table.actions(s)]):
                seat = rng.choice(acting)
                action = rng.choice(table.actions(seat))
                if isinstance(action, Assign) and rng.below(2):  # half the calls are correct
                    action = true_assignment(table, seat)
                result = table.act(seat, action, now)
            case 9 if anything := legal_actions(table.state, seat):
                result = table.act(seat, rng.choice(anything), now)
            case 10:
                table.disconnect(seat, now)
            case 11 | 12:
                table.connect(seat, now)
            case _:
                table.advance(now)
        if due is not None and due <= now:  # the first timer fired first, at its deadline
            fired = [e.received_us for e in table.entries[entries:] if "timer" in e.cause]
            handed = [r["at_us"] for r in table.log[count:] if r["type"] == "handover"]
            assert min(fired + handed) == due  # pyright: ignore[reportArgumentType]
        if isinstance(result, Rejected):
            assert table.log[-1]["type"] == "rejected"
            assert table.log[-1]["reason"] == result.reason
        assert table.turn_deadline() is None or table.state.current in table.people
        if phases is not None:
            phases.add(table.state.phase)
        if table.state.phase is Phase.RUNOUT:  # R.6.2: only the selected caller may call
            assert all(table.pressable(s) == () for s in SEATS)
        if rng.below(4):
            now += rng.below(5_000)  # sending takes a moment
            table.sent(now)
    table.sent(now)
    return table


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_every_game_the_table_plays_is_a_corpus_record(game_seed: int, policy_seed: int) -> None:
    rng = SplitMix64(policy_seed)
    people = tuple(s for s in SEATS if rng.below(4)) or (rng.choice(SEATS),)
    table = play(rng, new_table(game_seed, people), 3_000)
    game = read_corpus_record(record(table))
    assert len(game.steps) == len(table.entries)
    assert len(game.log) == len(table.log)
    handed = {row.seat for row in game.log if row.type == "handover"}
    assert handed == table.seated - table.people


def test_random_games_reach_every_phase() -> None:
    """The driver reaches run-out, votes and the end of the game, so the checks above meet
    them."""
    phases: set[Phase] = set()
    for seed in range(20):
        play(SplitMix64(seed), new_table(seed), 3_000, phases)
    assert phases == set(Phase)
