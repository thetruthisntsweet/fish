"""The website's bots (T3.5; R.8.8): how long a bot waits before it acts or presses Call.

A bot on the website waits before every action and every Call press. The wait comes from the
game's delay table (``fish_agents.delays``), by the kind of decision: the pilot site keeps
``uniform-1.5-4s-v1``, 1.5 to 4 seconds whatever the decision, and the study's site uses
the percentiles of the pilot's response times (``fish_server.settings.bot_delays``). Every
wait is drawn from the game's ``bot_delay`` stream at index ``event number x 6 + seat``
(docs/determinism.md §2), so a game's delays follow from its seed and its table's version,
which is recorded with it; a seat that waits more than once before the next event keeps
drawing from the same generator, as ``fish_agents.PolicyStreams`` does for the bots' choices.
"""

from fish_agents.delays import UNIFORM, DelayTable, load
from fish_rules.cards import Seat, check_seat
from fish_rules.rng import SplitMix64, stream


class DelayStreams:
    """The ``bot_delay`` generators of one game, one per seat per event number, and its
    table."""

    def __init__(self, game_seed: int, table: DelayTable | None = None) -> None:
        self.table = table or load(UNIFORM)
        self._seed = game_seed
        self._events = -1
        self._current: dict[Seat, SplitMix64] = {}

    def delay(self, seat: Seat, events: int, kind: str) -> int:
        """The next wait for ``seat``, deciding ``kind`` when ``events`` events have happened."""
        check_seat(seat)
        if events != self._events:
            if events < self._events:
                raise ValueError(f"event number went back from {self._events} to {events}")
            self._events = events
            self._current = {}
        if seat not in self._current:
            self._current[seat] = stream(self._seed, "bot_delay", events * 6 + seat)
        return self.table.draw(self._current[seat], kind)
