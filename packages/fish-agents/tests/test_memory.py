"""Agent memory (T2.8): settings as the corpus writes them, and a seat's memory remembering
each event once, with the view that first showed it, for full, last-k and no memory. Over
random games it remembers exactly what Layer 1's tracker does, and deduces the same."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_agents.memory import FULL, NONE, Memory, MemorySetting
from fish_rules.cards import SEATS
from fish_rules.corpus import BOT_MEMORY
from fish_rules.deduce.solve import deduce
from fish_rules.deduce.tracker import Tracker
from fish_rules.engine import replay
from fish_rules.events import Event
from fish_rules.playout import random_game
from fish_rules.rng import SplitMix64
from fish_rules.state import new_game
from fish_rules.view import PlayerView, latest_event, project

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games, a seat's every view: a fortieth of the profile's examples (10 in dev, 25 in
CI, 1,250 nightly)."""


def views(game_seed: int, policy_seed: int, seat: int) -> list[PlayerView]:
    """``seat``'s view at the deal and after every action of a random game."""
    out = [project(new_game(game_seed), seat, None)]
    last: Event | None = None
    for state, records in replay(game_seed, random_game(game_seed, policy_seed)):
        last = latest_event(records, last)
        out.append(project(state, seat, last))
    return out


GAME = views(1, 2, 4)


# ---------------------------------------------------------------- settings


def test_the_three_settings() -> None:
    assert (FULL.remembered, NONE.remembered, MemorySetting.last_k(8).remembered) == (None, 0, 8)
    assert (str(FULL), str(NONE), str(MemorySetting.last_k(8))) == ("full", "none", "last-8")


@pytest.mark.parametrize("setting", [FULL, NONE, MemorySetting.last_k(1), MemorySetting.last_k(30)])
def test_settings_are_written_as_the_corpus_writes_them(setting: MemorySetting) -> None:
    data = setting.as_corpus()
    assert set(data) == {"memory", "k"}
    assert data["memory"] in BOT_MEMORY
    assert MemorySetting.from_corpus(data["memory"], data["k"]) == setting


@pytest.mark.parametrize(
    ("kind", "k", "why"),
    [
        ("human", None, "one of full, last-k, none"),
        ("last-k", None, "needs k"),
        ("last-k", 0, "needs k"),
        ("last-k", True, "needs k"),
        ("full", 8, "only last-k memory has a k"),
    ],
)
def test_a_setting_that_is_not_one(kind: str, k: object, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        MemorySetting(kind, k)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(("memory", "k"), [(None, None), ("last-k", "8")])
def test_a_corpus_field_that_is_not_a_setting(memory: object, k: object) -> None:
    with pytest.raises(ValueError, match="not a bot's memory setting"):
        MemorySetting.from_corpus(memory, k)


# ---------------------------------------------------------------- one seat's memory


def test_full_memory_keeps_every_event_once_with_the_view_that_first_showed_it() -> None:
    memory = Memory(4, FULL)
    shown: dict[int, PlayerView] = {}
    for view in GAME:
        memory.observe(view)
        if view.last_event is not None:
            shown.setdefault(view.last_event.number, view)
    assert [event.number for event in memory.events] == list(range(len(shown)))
    assert memory.views == tuple(shown[n] for n in range(len(shown)))
    assert all(
        view.last_event == event for event, view in zip(memory.events, memory.views, strict=True)
    )
    assert memory.view == GAME[-1]


@pytest.mark.parametrize("k", [1, 3])
def test_last_k_memory_keeps_the_latest_k_events(k: int) -> None:
    full, limited = Memory(4, FULL), Memory(4, MemorySetting.last_k(k))
    for view in GAME:
        full.observe(view)
        limited.observe(view)
        assert limited.events == full.events[-k:]
        assert limited.views == full.views[-k:]


def test_no_memory_keeps_only_the_current_view() -> None:
    memory = Memory(4, NONE)
    for view in GAME:
        memory.observe(view)
    assert (memory.events, memory.views, memory.view) == ((), (), GAME[-1])
    assert memory.deduction == deduce(GAME[-1], [])


def test_a_missed_view_starts_a_new_run_and_a_new_game_forgets() -> None:
    memory = Memory(4, FULL)
    with_events = [view for view in GAME if view.last_event is not None]
    later = next(v for v in with_events if v.last_event and v.last_event.number == 5)
    memory.observe(with_events[0])
    memory.observe(later)  # events 1 to 4 were never shown
    assert [event.number for event in memory.events] == [5]
    memory.observe(GAME[0])  # the deal of a game: nothing has happened
    assert memory.events == ()


def test_the_deduction_is_layer_1_and_is_kept_until_something_changes() -> None:
    memory = Memory(4, MemorySetting.last_k(6))
    memory.observe(GAME[40])  # mid-game, with nothing earlier remembered
    first = memory.deduction
    assert first == deduce(GAME[40], memory.events)
    assert memory.deduction is first
    memory.observe(GAME[40])
    assert memory.deduction is first


def test_memory_refuses_misuse() -> None:
    memory = Memory(4, FULL)
    with pytest.raises(ValueError, match="no view has been shown yet"):
        memory.deduction  # noqa: B018
    with pytest.raises(ValueError, match="seat 4's, not seat 0's"):
        memory.observe(project(new_game(1), 0, None))


# ---------------------------------------------------------------- over random games


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64, U64)
def test_memory_remembers_what_the_tracker_does(
    game_seed: int, policy_seed: int, choice_seed: int
) -> None:
    """Every view of a random game, or nine in ten of them, under a random setting: the
    events remembered are the tracker's, and so is the deduction."""
    rng = SplitMix64(choice_seed)
    seat = rng.below(len(SEATS))
    setting = rng.choice(
        (FULL, NONE, MemorySetting.last_k(1), MemorySetting.last_k(1 + rng.below(30)))
    )
    memory, tracker = Memory(seat, setting), Tracker(seat, remembered=setting.remembered)
    skip = rng.below(2)
    for view in views(game_seed, policy_seed, seat):
        if skip and not rng.below(10):
            continue
        memory.observe(view)
        deduction = tracker.observe(view)
        assert memory.events == tuple(tracker.events)
        if view.last_event is not None and rng.below(8) == 0:
            assert memory.deduction == deduction
