"""Agents with memory (T2.8): ``Remembering`` gives a ``MemoryAgent`` one memory per seat, and
``play_game`` shows every observer every view, so a full-memory agent remembers the whole
game, unbroken, at every decision; last-k and no memory remember what they should; and memory
changes nothing for an agent that does not use it."""

from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_agents.b0 import B0
from fish_agents.base import Observer
from fish_agents.memory import FULL, NONE, Memory, MemorySetting, Remembering
from fish_agents.play import play_game
from fish_rules.codec import action_from_data
from fish_rules.engine import replay
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.rng import SplitMix64
from fish_rules.view import PlayerView

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games of six agents: a fortieth of the profile's examples (10 in dev, 25 in CI,
1,250 nightly)."""


@dataclass
class Notebook:
    """A ``MemoryAgent`` that plays as B0 does and writes down, at every decision, what its
    memory held."""

    seen: list[tuple[int, tuple[Event, ...], PlayerView]] = field(default_factory=list)

    def act(self, view: PlayerView, memory: Memory, rng: SplitMix64) -> int:
        assert memory.view == view
        self.seen.append((view.seat, memory.events, view))
        return B0().act(view, rng)


def events_of(record: dict[str, object]) -> list[Event]:
    """Every event of a recorded game, in order."""
    recorded = record["actions"]
    assert isinstance(recorded, list)
    seed = int(str(record["seed"]))
    return [
        r
        for _, records in replay(seed, [action_from_data(a) for a in recorded])
        for r in records
        if isinstance(r, AskEvent | CallEvent | ChoiceEvent)
    ]


def test_remembering_is_an_observing_agent() -> None:
    assert isinstance(Remembering(Notebook(), FULL), Observer)
    assert not isinstance(B0(), Observer)


def test_full_memory_holds_every_event_so_far_at_every_decision() -> None:
    notebook = Notebook()
    record = play_game([Remembering(notebook, FULL)] * 6, 11)
    events = events_of(record)
    assert notebook.seen
    for _seat, remembered, view in notebook.seen:
        count = 0 if view.last_event is None else view.last_event.number + 1
        assert list(remembered) == events[:count]


@pytest.mark.parametrize("setting", [NONE, MemorySetting.last_k(1), MemorySetting.last_k(5)])
def test_shorter_memories_hold_the_latest_events(setting: MemorySetting) -> None:
    notebook = Notebook()
    record = play_game([Remembering(notebook, setting)] * 6, 11)
    events = events_of(record)
    keep = setting.remembered
    assert keep is not None
    for _seat, remembered, view in notebook.seen:
        count = 0 if view.last_event is None else view.last_event.number + 1
        assert list(remembered) == (events[:count][-keep:] if keep else [])


def test_each_seat_has_its_own_memory() -> None:
    shared = Remembering(Notebook(), FULL)
    play_game([shared] * 6, 3)
    assert sorted(shared.memories) == [0, 1, 2, 3, 4, 5]
    assert {memory.seat for memory in shared.memories.values()} == {0, 1, 2, 3, 4, 5}
    first = {memory.views[0].hand for memory in shared.memories.values()}  # just after event 0
    assert len(first) == 6  # six seats' views, not one seat's six times


@dataclass
class Watcher:
    """B0 that also counts the views it is shown, to see that ``play_game`` shows them."""

    shown: list[PlayerView] = field(default_factory=list)

    def observe(self, view: PlayerView) -> None:
        self.shown.append(view)

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        return B0().act(view, rng)


def test_play_game_shows_every_observer_every_event() -> None:
    watchers = [Watcher() for _ in range(6)]
    record = play_game(watchers, 5)
    numbers = {event.number for event in events_of(record)}
    for seat, watcher in enumerate(watchers):
        assert {view.seat for view in watcher.shown} == {seat}
        shown = {view.last_event.number for view in watcher.shown if view.last_event is not None}
        assert shown >= numbers - {max(numbers)}  # the last event ends the game


def test_memory_changes_nothing_for_an_agent_that_ignores_it() -> None:
    """Notebook chooses as B0 does, so with any memory it plays B0's game: being shown every
    view draws nothing from the game's generators."""
    b0 = play_game([B0()] * 6, 21)
    for setting in (FULL, NONE, MemorySetting.last_k(3)):
        assert play_game([Remembering(Notebook(), setting)] * 6, 21) == b0


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_a_full_memory_is_unbroken_at_every_decision(game_seed: int, choice_seed: int) -> None:
    """Over random games, with each seat remembering under its own random setting: at every
    decision, a seat's memory is exactly the latest events it may keep, with no gap."""
    rng = SplitMix64(choice_seed)
    options = (FULL, NONE, MemorySetting.last_k(1), MemorySetting.last_k(1 + rng.below(20)))
    notebooks = [Notebook() for _ in range(6)]
    agents = [Remembering(notebook, rng.choice(options)) for notebook in notebooks]
    events = events_of(play_game(agents, game_seed))
    for agent, notebook in zip(agents, notebooks, strict=True):
        keep = agent.setting.remembered
        for _seat, remembered, view in notebook.seen:
            count = 0 if view.last_event is None else view.last_event.number + 1
            so_far = events[:count]
            expected = so_far if keep is None else so_far[-keep:] if keep else []
            assert list(remembered) == expected
