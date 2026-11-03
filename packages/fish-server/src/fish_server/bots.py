"""The website's bots (T3.5; R.8.8): how long a bot waits before it acts or presses Call.

A bot on the website waits before every action and every Call press. Until pilot data
exists (T4.2) the wait is drawn uniformly from 1.5 to 4 seconds, in whole microseconds:
``BOT_DELAY_MIN_US + below(BOT_DELAY_MAX_US - BOT_DELAY_MIN_US + 1)``. It is drawn from the
game's ``bot_delay`` stream at index ``event number x 6 + seat`` (docs/determinism.md §2),
so a game's delays follow from its seed; a seat that waits more than once before the next
event keeps drawing from the same generator, as ``fish_agents.PolicyStreams`` does for the
bots' choices.
"""

from typing import Final

from fish_rules.cards import Seat, check_seat
from fish_rules.rng import SplitMix64, stream

BOT_DELAY_MIN_US: Final = 1_500_000
BOT_DELAY_MAX_US: Final = 4_000_000
"""R.8.8: until pilot data exists, a bot waits 1.5 to 4 seconds before acting."""


def draw_delay(rng: SplitMix64) -> int:
    """One wait, in microseconds, uniform from ``BOT_DELAY_MIN_US`` to ``BOT_DELAY_MAX_US``."""
    return BOT_DELAY_MIN_US + rng.below(BOT_DELAY_MAX_US - BOT_DELAY_MIN_US + 1)


class DelayStreams:
    """The ``bot_delay`` generators of one game, one per seat per event number."""

    def __init__(self, game_seed: int) -> None:
        self._seed = game_seed
        self._events = -1
        self._current: dict[Seat, SplitMix64] = {}

    def delay(self, seat: Seat, events: int) -> int:
        """The next wait for ``seat`` when ``events`` events have happened."""
        check_seat(seat)
        if events != self._events:
            if events < self._events:
                raise ValueError(f"event number went back from {self._events} to {events}")
            self._events = events
            self._current = {}
        if seat not in self._current:
            self._current[seat] = stream(self._seed, "bot_delay", events * 6 + seat)
        return draw_delay(self._current[seat])
