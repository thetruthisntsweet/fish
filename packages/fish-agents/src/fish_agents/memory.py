"""What an agent remembers (T2.8).

Every seat is shown every event as it happens, but each view holds only the most recent one
(R.2.2, R.2.5), so remembering is the player's business. Memory is a property of the agent,
not of the game (Plan §3): an agent remembers everything it has been shown, only the latest
k events, or nothing beyond its current view.

**k counts events**, not views. A seat is shown the same event in many views (the window
after it, the turn, a call's assignment), and how many depends on the platform: the
environment asks every seat in every window, the website opens a window only when someone
presses Call (R.8.9). Counting events gives last-k the same meaning on both, and in the
corpus (D57).

``MemorySetting`` is the setting, written in the corpus as ``memory`` and ``k``
(``fish-corpus-v2``, docs/corpus.md §4). ``Memory`` is one seat's memory: shown every view,
it keeps each event once, with the view that first showed it, and from them gives Layer 1's
deduction (``fish_rules.deduce``). Like Layer 1 it keeps an unbroken run of events: if a
view's event is not the one after the last remembered (the seat missed a view), it starts a
new run there.

An agent with memory is a ``MemoryAgent``: it is given its seat's memory as well as its view,
``act(view, memory, rng)``. ``Remembering(agent, setting)`` makes it an ordinary ``Agent``
that keeps one ``Memory`` per seat it plays, and an ``Observer``, so whoever runs it can show
it every view (``fish_agents.play.play_game`` does; the server's bots will, T3.5).

This module needs only fish-rules, so the server can give its bots memory (T3.5).
"""

from dataclasses import dataclass
from typing import Final, Protocol

from fish_rules.cards import Seat
from fish_rules.corpus import BOT_MEMORY
from fish_rules.deduce.solve import Deduction, deduce
from fish_rules.events import Event
from fish_rules.rng import SplitMix64
from fish_rules.view import PlayerView


@dataclass(frozen=True, slots=True)
class MemorySetting:
    """``full``, ``none``, or ``last-k`` with its ``k`` (1 or more events)."""

    kind: str
    k: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in BOT_MEMORY:
            raise ValueError(f"memory is one of {', '.join(BOT_MEMORY)}, not {self.kind!r}")
        if self.kind == "last-k":
            if not isinstance(self.k, int) or isinstance(self.k, bool) or self.k < 1:
                raise ValueError(
                    f"last-k memory needs k, a whole number of events 1 or more, not {self.k!r}"
                )
        elif self.k is not None:
            raise ValueError(f"only last-k memory has a k, not {self.kind}")

    @classmethod
    def last_k(cls, k: int) -> MemorySetting:
        """Remember the latest ``k`` events."""
        return cls("last-k", k)

    @property
    def remembered(self) -> int | None:
        """How many events are kept: None for all of them."""
        return None if self.kind == "full" else 0 if self.kind == "none" else self.k

    def as_corpus(self) -> dict[str, object]:
        """The setting as a corpus seat writes it: ``{"memory": ..., "k": ...}``."""
        return {"memory": self.kind, "k": self.k}

    @classmethod
    def from_corpus(cls, memory: object, k: object) -> MemorySetting:
        """The setting a corpus seat records; ValueError for a person's ``human`` or anything
        else that is not a bot's memory."""
        if not isinstance(memory, str) or (k is not None and not isinstance(k, int)):
            raise ValueError(f"not a bot's memory setting: memory {memory!r}, k {k!r}")
        return cls(memory, k)

    def __str__(self) -> str:
        return f"last-{self.k}" if self.kind == "last-k" else self.kind


FULL: Final = MemorySetting("full")
"""Remember everything shown."""

NONE: Final = MemorySetting("none")
"""Remember nothing beyond the current view."""


class Memory:
    """One seat's memory under a setting. Show it every view the seat is shown."""

    def __init__(self, seat: Seat, setting: MemorySetting) -> None:
        self.seat = seat
        self.setting = setting
        self._entries: list[tuple[Event, PlayerView]] = []
        self._view: PlayerView | None = None
        self._latest: tuple[object, Deduction] | None = None

    def observe(self, view: PlayerView) -> None:
        """Remember what ``view`` shows: its event, if it is new, with the view itself."""
        if view.seat != self.seat:
            raise ValueError(f"this memory is seat {self.seat}'s, not seat {view.seat}'s")
        self._view = view
        event = view.last_event
        entries = self._entries
        if event is None:
            entries = []  # nothing has happened yet: a new game
        elif not entries or event.number != entries[-1][0].number:
            follows = bool(entries) and event.number == entries[-1][0].number + 1
            entries = [*entries, (event, view)] if follows else [(event, view)]
        keep = self.setting.remembered
        self._entries = entries if keep is None else entries[-keep:] if keep else []

    @property
    def events(self) -> tuple[Event, ...]:
        """The events remembered, oldest first: an unbroken run ending at the latest view's."""
        return tuple(event for event, _ in self._entries)

    @property
    def views(self) -> tuple[PlayerView, ...]:
        """For each remembered event, the view that first showed it."""
        return tuple(view for _, view in self._entries)

    @property
    def view(self) -> PlayerView:
        """The latest view shown."""
        if self._view is None:
            raise ValueError("no view has been shown yet")
        return self._view

    @property
    def deduction(self) -> Deduction:
        """Layer 1 from the latest view and what is remembered, worked out when first asked
        for and kept until a view changes something it uses."""
        view = self.view
        key = (view.last_event, view.hand, view.hand_sizes, view.scored_by, len(self._entries))
        if self._latest is None or self._latest[0] != key:
            self._latest = (key, deduce(view, self.events))
        return self._latest[1]


class MemoryAgent(Protocol):
    """A player that is given what it remembers as well as what it sees. ``act`` must return
    one of ``view.legal``."""

    def act(self, view: PlayerView, memory: Memory, rng: SplitMix64) -> int:
        """The index of the action to take, given this seat's view, its memory (which has
        already been shown ``view``) and a generator for any random choice."""
        ...


class Remembering:
    """``agent`` with memory ``setting``: an ``Agent``, and an ``Observer`` to be shown every
    view. One instance may play several seats; each seat has its own memory."""

    def __init__(self, agent: MemoryAgent, setting: MemorySetting) -> None:
        self.agent = agent
        self.setting = setting
        self.memories: dict[Seat, Memory] = {}

    def memory(self, seat: Seat) -> Memory:
        """``seat``'s memory, empty until the seat is shown a view."""
        if seat not in self.memories:
            self.memories[seat] = Memory(seat, self.setting)
        return self.memories[seat]

    def observe(self, view: PlayerView) -> None:
        """Show ``view`` to its seat's memory."""
        self.memory(view.seat).observe(view)

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        """Remember ``view``, then let the agent choose with its seat's memory."""
        self.observe(view)
        return self.agent.act(view, self.memory(view.seat), rng)
