"""Layer 1 for an agent as a game goes on (T2.7).

An agent sees one view at a time, and each view holds only the most recent event (R.2.2).
``Tracker`` remembers the events a seat has been shown and gives its deduction for each new
view, so an agent needs only to pass its views along:

    tracker = Tracker(seat)
    for view in views:
        deduction = tracker.observe(view)

The same event arrives in many views (a window, a call's assignment and a choice each show
the last event again), and is remembered once. ``remembered`` keeps only the latest events,
for a last-k memory (T2.8); 0 remembers none. If a view's event is not the one after the last
remembered (the seat was not shown every view), the run starts again from it, since only an
unbroken run of events says where cards are (``fish_rules.deduce.history``).
"""

from fish_rules.cards import Seat
from fish_rules.deduce.solve import Deduction, deduce
from fish_rules.events import Event
from fish_rules.view import PlayerView


class Tracker:
    """Remembers what one seat has been shown, and deduces from it."""

    def __init__(self, seat: Seat, *, remembered: int | None = None, use_hand: bool = True):
        if remembered is not None and remembered < 0:
            raise ValueError(f"remembered must be a number of events, 0 or more, not {remembered}")
        self.seat = seat
        self.remembered = remembered
        self.use_hand = use_hand
        self.events: list[Event] = []
        self._latest: tuple[object, Deduction] | None = None

    def _remember(self, event: Event | None) -> None:
        if event is None:
            self.events = []
        elif not self.events or event.number != self.events[-1].number:
            follows = bool(self.events) and event.number == self.events[-1].number + 1
            self.events = [*self.events, event] if follows else [event]
        if self.remembered is not None:
            self.events = self.events[-self.remembered :] if self.remembered else []

    def observe(self, view: PlayerView) -> Deduction:
        """Remember ``view``'s event, if it is new, and deduce from ``view`` and what is
        remembered. A view that changes nothing Layer 1 uses gives the same deduction back."""
        if view.seat != self.seat:
            raise ValueError(f"this tracker follows seat {self.seat}, not seat {view.seat}")
        self._remember(view.last_event)
        key = (view.last_event, view.hand, view.hand_sizes, view.scored_by, len(self.events))
        if self._latest is None or self._latest[0] != key:
            self._latest = (key, deduce(view, self.events, use_hand=self.use_hand))
        return self._latest[1]
