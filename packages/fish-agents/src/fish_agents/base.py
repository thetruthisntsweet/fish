"""What an agent is, and where its randomness comes from (T5.1).

An ``Agent`` is given its seat's view (``fish_rules.view.PlayerView``: everything that seat
may know, R.2) and a random generator, and returns the index of the action it takes
(``fish_rules.action_index``). It is never given the game seed, which would reveal the deal.

``PolicyStreams`` hands out those generators. The generator for a decision comes from the
game's ``bot_policy`` stream (docs/determinism.md §2) at index ``event number x 6 + seat``,
so a game played by seeded agents is reproduced exactly from its game seed, on the website
(T3.5) as in the environment. A seat that decides more than once before the next event (a
window answer, then the assignment of its call) keeps drawing from the same generator, so no
two decisions repeat each other's draws.

This module imports nothing outside fish-rules, so the server can run agents as bots.
"""

from typing import Protocol

from fish_rules.cards import Seat, check_seat
from fish_rules.rng import SplitMix64, stream
from fish_rules.view import PlayerView


class Agent(Protocol):
    """A player. ``act`` must return one of ``view.legal``."""

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        """The index of the action to take, given what this seat may know and a generator for
        any random choice."""
        ...


class PolicyStreams:
    """The ``bot_policy`` generators of one game, one per seat per event number."""

    def __init__(self, game_seed: int) -> None:
        self._seed = game_seed
        self._events = -1
        self._current: dict[Seat, SplitMix64] = {}

    def for_decision(self, seat: Seat, events: int) -> SplitMix64:
        """The generator for ``seat``'s decision when ``events`` events have happened. The
        same seat gets the same generator, continuing its draws, until the next event."""
        check_seat(seat)
        if events != self._events:
            if events < self._events:
                raise ValueError(f"event number went back from {self._events} to {events}")
            self._events = events
            self._current = {}
        if seat not in self._current:
            self._current[seat] = stream(self._seed, "bot_policy", events * 6 + seat)
        return self._current[seat]
