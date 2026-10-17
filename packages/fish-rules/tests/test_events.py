"""Tests for fish_rules.events: actions and records, and which records players may see."""

from dataclasses import FrozenInstanceError, fields, replace

import pytest

from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    Assign,
    Call,
    CallEvent,
    ChoiceEvent,
    Choose,
    CloseWindow,
    DeclarationDiscarded,
    Declare,
    Declared,
    GameOver,
    OpenWindow,
    Pass,
    Record,
    RunoutCallerSelected,
    SeedChose,
    Visibility,
    Vote,
    VoteCast,
    WindowClosed,
    WindowOpened,
)
from fish_rules.state import CallSource, Outcome

PUBLIC_RECORDS: list[Record] = [
    AskEvent(number=0, asker=1, target=4, card=7, success=True),
    CallEvent(
        number=1,
        caller=2,
        set_id=1,
        source=CallSource.WINDOW,
        assignment=(0, 0, 1, 1, 2, 2),
        holders=(0, 0, 1, 1, 2, 3),
        correct=False,
        scored_by=1,
    ),
    ChoiceEvent(number=2, team=1, seat=4),
    WindowOpened(index=3),
    WindowClosed(index=3, caller=5, set_id=8),
    WindowClosed(index=4, caller=None, set_id=None),
    RunoutCallerSelected(window=5, seat=0),
    GameOver(outcome=Outcome.FINISHED, winner=0),
]

LOG_ONLY_RECORDS: list[Record] = [
    Declared(window=3, seat=5, set_id=8),
    DeclarationDiscarded(window=3, seat=1, set_id=2),
    VoteCast(call_event=1, seat=3, chosen=4),
    SeedChose(call_event=1, among=(3, 4, 5), chosen=4),
]


@pytest.mark.parametrize("record", PUBLIC_RECORDS, ids=lambda r: type(r).__name__)
def test_r2_2_events_and_window_results_are_public(record: Record) -> None:
    """R.2.2: the most recent event is public; R.2.3: revealed holders are public;
    R.8.3: that a window opened, and the call that proceeds, are shown to all players."""
    assert record.visibility is Visibility.PUBLIC


@pytest.mark.parametrize("record", LOG_ONLY_RECORDS, ids=lambda r: type(r).__name__)
def test_r4_3_r5_2_hidden_records_are_log_only(record: Record) -> None:
    """R.4.3: discarded declarations are not shown but are logged. R.5.2: individual votes are
    logged; only the outcome is shown. R.8.3: who declared, and which set, is not shown while
    the window is open."""
    assert record.visibility is Visibility.LOG_ONLY


def test_r4_2_only_asks_calls_and_choices_are_numbered_events() -> None:
    """R.4.2: an event is an ask and its answer, a call and its result, or an after-call
    choice. Only these carry an event number (docs/determinism.md §8)."""
    numbered = {
        type(record).__name__
        for record in PUBLIC_RECORDS + LOG_ONLY_RECORDS
        if "number" in {field.name for field in fields(record)}
    }
    assert numbered == {"AskEvent", "CallEvent", "ChoiceEvent"}


def test_visibility_is_not_a_field() -> None:
    """Visibility belongs to the record type, not to each record, so it cannot be set wrong."""
    for record in PUBLIC_RECORDS + LOG_ONLY_RECORDS:
        assert "visibility" not in {field.name for field in fields(record)}


@pytest.mark.parametrize(
    "action",
    [
        Ask(seat=0, target=3, card=5),
        Call(seat=0, set_id=2),
        Declare(seat=4, set_id=2),
        Pass(seat=4),
        Assign(seat=0, holders=(0, 1, 2, 0, 1, 2)),
        Choose(seat=0, chosen=1),
        Vote(seat=3, chosen=5),
        OpenWindow(),
        CloseWindow(),
    ],
    ids=lambda a: type(a).__name__,
)
def test_actions_are_immutable_values(action: Action) -> None:
    """Actions are replayed from the log, so they are plain, comparable, immutable values."""
    assert replace(action) == action
    assert hash(replace(action)) == hash(action)
    with pytest.raises(FrozenInstanceError):
        setattr(action, "seat", 9)  # noqa: B010
