"""The table: the engine under website mechanics (T3.1). Presses open 1-second windows, the
assignment and the after-call choice time out, stale presses, discarded actions and illegal
inputs are rejected and logged, and every timer runs on the server clock. Over random games
with random inputs at random times, every game the table plays is a corpus record that
reads back."""

from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
    SECOND_US,
    WINDOW_US,
    Accepted,
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
PEOPLE: Final = [
    {"person": f"p{s}", "cohort": False, "agent": None, "memory": "human", "k": None, "note": "no"}
    for s in SEATS
]


def record(table: Table) -> dict[str, object]:
    """The table's game as a corpus record, read back."""
    outcome = table.state.outcome
    completion = "abandoned" if outcome is None else str(outcome)
    data = table.record(game=GAME | {"completion": completion}, seats=PEOPLE)
    read_corpus_record(data)
    return data


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
    table = Table(1)
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
    table = Table(1)
    set_id = table.state.sets_in_play()[2]
    table.press(4, set_id, None, 0)
    for seat in SEATS:
        view = table.view(seat)
        assert view.window_open
        assert view.own_declaration == (set_id if seat == 4 else None)


def test_r8_3_an_action_sent_while_a_window_is_open_is_discarded() -> None:
    table = Table(1)
    current = table.state.current
    assert current is not None
    ask = table.actions(current)[0]
    table.press(4, table.state.sets_in_play()[0], None, 0)
    assert table.actions(current) == ()
    assert table.act(current, ask, 10) == Rejected("illegal", discarded=True)
    assert table.log[-1] | {} == {
        "type": "rejected",
        "after": 2,
        "at_us": 10,
        "seat": current,
        "input": {"type": "Ask", "seat": ask.seat, "target": ask.target, "card": ask.card},  # pyright: ignore[reportAttributeAccessIssue]
        "reason": "illegal",
    }


def test_r8_3_presses_during_an_assignment_or_a_choice_are_rejected() -> None:
    table = Table(1)
    closed = to_assignment(table)
    assert table.pressable(0) == ()
    assert table.press(0, table.state.sets_in_play()[0], None, closed + 1) == Rejected("illegal")
    table.advance(closed + ASSIGN_US)
    assert table.state.phase in (Phase.CHOOSE, Phase.VOTE)
    assert table.press(3, table.state.sets_in_play()[0], 0, closed + ASSIGN_US + 1) == Rejected(
        "illegal"
    )
    assert [row["reason"] for row in table.log] == ["illegal", "illegal"]


def test_r4_3_on_a_turn_a_call_starts_with_a_press() -> None:
    table = Table(1)
    current = table.state.current
    assert current is not None
    assert all(isinstance(a, Ask) for a in table.actions(current))
    call = Call(current, table.state.sets_in_play()[0])
    assert call in legal_actions(table.state, current)  # the engine allows it, the website not
    assert table.act(current, call, 0) == Rejected("illegal")


# ---------------------------------------------------------------- timers (R.4.3, R.5.2, R.8.5)


def test_r4_3_the_caller_has_30_seconds_to_assign() -> None:
    table = Table(1)
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
    table = Table(1)
    closed = to_assignment(table)
    table.advance(closed + ASSIGN_US)
    assert table.state.phase in (Phase.CHOOSE, Phase.VOTE)
    assert table.deadline() == closed + ASSIGN_US + CHOICE_US
    assert table.advance(closed + ASSIGN_US + CHOICE_US) == 1
    entry = table.entries[-1]
    assert (entry.action, entry.cause) == (ChoiceTimeout(), {"timer": "choice"})
    assert table.state.phase is Phase.TURN
    assert table.deadline() is None


def test_r8_5_timers_run_on_the_server_clock_however_late_they_are_checked() -> None:
    """A timer's action is received at its deadline on the server clock, not when the table
    was next asked; an input that arrives later first lets every timer due by then fire."""
    table = Table(1)
    table.press(1, table.state.sets_in_play()[0], None, 7)
    late = 7 + WINDOW_US + ASSIGN_US + 3 * SECOND_US
    assert table.press(4, table.state.sets_in_play()[0], None, late) == Rejected("illegal")
    assert [(type(e.action), e.received_us) for e in table.entries[2:]] == [
        (CloseWindow, 7 + WINDOW_US),
        (AssignTimeout, 7 + WINDOW_US + ASSIGN_US),
    ]
    assert table.log[-1]["after"] == 4  # the press came after both timers


def test_an_assignment_in_time_stops_the_timer() -> None:
    table = Table(1)
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
        table = Table(seed)
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
        table = Table(seed)
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
    table = Table(1)
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
    table = Table(1)
    current = table.state.current
    assert current is not None
    other = next(s for s in SEATS if s != current)
    foreign = Ask(other, current, 0)
    assert table.act(other, foreign, 1) == Rejected("illegal")
    assert table.act(current, Pass(current), 2) == Rejected("illegal")  # nobody passes
    assert table.act(current, Declare(current, 0), 3) == Rejected("illegal")  # declare by pressing
    assert table.act(current, table.actions(current)[0], 4) == Accepted(1)
    assert [row["at_us"] for row in table.log] == [1, 2, 3]


@pytest.mark.parametrize(
    ("set_id", "seen"),
    [(9, None), (-1, None), (True, None), (0, 0), (0, -1), (0, True)],
)
def test_a_press_that_cannot_be_read_is_malformed(set_id: int, seen: int | None) -> None:
    table = Table(1)
    assert table.press(0, set_id, seen, 0) == Rejected("malformed")


def test_control_actions_and_actions_for_another_seat_are_malformed() -> None:
    table = Table(1)
    current = table.state.current
    assert current is not None
    other = next(s for s in SEATS if s != current)
    assert table.act(current, OpenWindow(), 0) == Rejected("malformed")
    assert table.act(other, table.actions(current)[0], 0) == Rejected("malformed")
    assert table.reject(3, "{not json", "malformed", 0) == Rejected("malformed")
    assert [row["reason"] for row in table.log] == ["malformed"] * 3
    assert table.log[-1]["input"] == "{not json"


def test_inputs_after_the_game_are_rejected() -> None:
    table = play(SplitMix64(3), Table(3), 5_000)
    if table.state.phase is Phase.OVER:
        assert table.press(0, 0, None, 10**12) == Rejected("illegal")
        assert table.actions(0) == ()


def test_the_table_refuses_misuse() -> None:
    table = Table(1)
    table.advance(100)
    with pytest.raises(ValueError, match="time never goes back"):
        table.advance(99)
    with pytest.raises(ValueError, match="no seat"):
        table.reject(6, None, "malformed", 100)
    table.press(0, 0, None, 100)
    with pytest.raises(ValueError, match="every action must be sent"):
        table.record(game=GAME | {"completion": "abandoned"}, seats=PEOPLE)
    assert table.sent(150) == 2
    assert table.sent(160) == 0
    assert [e.sent_us for e in table.entries] == [150, 150]


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
    """Random inputs from random seats at random times, legal or not, with updates sent at
    random moments. Checks, as it goes, what the table promises about timers and rejections."""
    now = 0
    for _ in range(steps):
        if table.state.phase is Phase.OVER:
            break
        now += rng.below(3 * SECOND_US) if rng.below(6) else rng.below(40 * SECOND_US)
        due, entries, rows = table.deadline(), len(table.entries), len(table.log)
        seat = rng.choice(SEATS)
        match rng.below(12):
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
            case _:
                result = None
                table.advance(now)
        if due is not None and due <= now:  # the running timer fired first, at its deadline
            assert table.entries[entries].received_us == due
            assert table.entries[entries].cause.get("timer") is not None
        if isinstance(result, Rejected):
            assert len(table.log) == rows + 1
            assert table.log[-1]["reason"] == result.reason
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
    table = play(SplitMix64(policy_seed), Table(game_seed), 3_000)
    data = record(table)
    game = read_corpus_record(data)
    assert len(game.steps) == len(table.entries)
    assert [row.type for row in game.log] == ["rejected"] * len(table.log)


def test_random_games_reach_every_phase() -> None:
    """The driver reaches run-out, votes and the end of the game, so the checks above meet
    them."""
    phases: set[Phase] = set()
    for seed in range(20):
        play(SplitMix64(seed), Table(seed), 3_000, phases)
    assert phases == set(Phase)
