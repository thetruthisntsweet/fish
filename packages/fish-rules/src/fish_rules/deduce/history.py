"""What a seat's remembered events say about the deal (Layer 1, T2.7).

Cards move only in public: a successful ask shows which card went from whom to whom, and a
call reveals the holder of each of its six cards before they leave play (R.2.2, R.2.3,
R.3.3, R.4.5). So a card that has not moved since some moment is still with whoever held it
then. Every fact in a run of remembered events is therefore a constraint on a single unknown,
the deal at the moment just before the first remembered event, called the *anchor* here:

- an ask for a card shows that the asker did not hold it (R.3.2);
- an ask shows that the asker held at least one other card of its set (R.3.2);
- a successful ask shows that the target held the card; a failed one, that it did not
  (R.3.3);
- a call shows who held each of its six cards (R.2.3);
- hand sizes, the scored sets and the observer's own hand are shown now (R.2.1, R.2.2).

``constraints`` collects these. With the whole game remembered, the anchor is the deal itself;
with only the last few events (a last-k memory, T2.8), it is the deal as it stood before them,
whose hand sizes and observer's hand are worked back from the current view. Nothing else in a
view or an event depends on where the cards are: windows, declarations, passes and the
after-call choice depend only on public hand sizes. Deciding which deals satisfy all the
constraints at once is the solver's job (T2.7 subtask 2).

Seats are written as bit masks here: bit ``s`` is set when seat ``s`` is allowed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fish_rules.cards import (
    CARDS,
    HAND_SIZE,
    NUM_CARDS,
    SEATS,
    Card,
    Seat,
    SetId,
    set_cards,
    set_of,
)
from fish_rules.events import AskEvent, CallEvent, Event
from fish_rules.view import PlayerView

type SeatMask = int
"""A set of seats: bit ``s`` is set when seat ``s`` is in it."""

ALL_SEATS: Final[SeatMask] = (1 << len(SEATS)) - 1


def seat_mask(seats: Sequence[Seat]) -> SeatMask:
    """The mask holding exactly ``seats``."""
    mask = 0
    for seat in seats:
        mask |= 1 << seat
    return mask


def seats_in(mask: SeatMask) -> tuple[Seat, ...]:
    """The seats in ``mask``, ascending."""
    return tuple(seat for seat in SEATS if mask >> seat & 1)


class HistoryError(ValueError):
    """The events do not fit the view: they are not one unbroken run ending at its most
    recent event, or no deal could have produced them."""


@dataclass(frozen=True, slots=True)
class AtLeastOne:
    """``seat`` held at least one of ``cards`` at the anchor (an ask by ``seat``, R.3.2)."""

    seat: Seat
    cards: tuple[Card, ...]


@dataclass(frozen=True, slots=True)
class Constraints:
    """What ``observer`` knows about the deal at the anchor, from its view and the events it
    remembers. ``observer`` is None for the public view, which uses no one's hand.

    ``start``: the number of the first remembered event; the anchor is just before it, so
    ``start`` 0 means the whole game is remembered and the anchor is the deal.
    ``sizes``: each seat's hand size at the anchor.
    ``allowed``: for each card, the seats that may have held it at the anchor, as a mask;
    0 for cards already out of play then. Every constraint about a single card is here.
    ``at_least_one``: the remaining constraints, at most one for each seat and set.
    ``moved``: for each card still in play that moved since the anchor, the seat holding it
    now (it moves only in public); None otherwise. A card in play that has not moved is
    still with its holder at the anchor.
    ``in_play``: for each card, whether its set is still in play now.
    """

    observer: Seat | None
    start: int
    sizes: tuple[int, ...]
    allowed: tuple[SeatMask, ...]
    at_least_one: tuple[AtLeastOne, ...]
    moved: tuple[Seat | None, ...]
    in_play: tuple[bool, ...]


def _check_run(view: PlayerView, events: Sequence[Event]) -> int:
    """The number of the first remembered event, once the events are checked to be one
    unbroken run ending at the view's most recent event."""
    last = view.last_event
    if last is None:
        if events:
            raise HistoryError("the view has no event yet, so nothing can be remembered")
        return 0
    if not events:
        return last.number + 1
    start = events[0].number
    for offset, event in enumerate(events):
        if event.number != start + offset:
            raise HistoryError(
                f"event {event.number} follows event {start + offset - 1}; the remembered "
                "events must be one unbroken run"
            )
    if events[-1] != last:
        raise HistoryError("the remembered events must end at the view's most recent event")
    return start


def _anchor(
    view: PlayerView, events: Sequence[Event], observer: Seat | None, start: int
) -> tuple[list[int], set[Card], list[bool]]:
    """Hand sizes, the observer's hand and the cards in play at the anchor, worked back from
    the view through the remembered events."""
    sizes = list(view.hand_sizes)
    hand = set(view.hand) if observer is not None else set[Card]()
    in_play = [view.scored_by[set_of(card)] is None for card in CARDS]
    for event in reversed(events):
        if isinstance(event, AskEvent) and event.success:
            sizes[event.asker] -= 1
            sizes[event.target] += 1
            if observer == event.asker:
                hand.discard(event.card)
            elif observer == event.target:
                hand.add(event.card)
        elif isinstance(event, CallEvent):
            for card, holder in zip(set_cards(event.set_id), event.holders, strict=True):
                sizes[holder] += 1
                in_play[card] = True
                if observer == holder:
                    hand.add(card)
    ok = min(sizes) >= 0 and sum(sizes) == sum(in_play)
    if observer is not None:
        ok = ok and len(hand) == sizes[observer] and all(in_play[card] for card in hand)
    if start == 0:
        ok = ok and all(size == HAND_SIZE for size in sizes)
    if not ok:
        raise HistoryError("no deal fits the view and the remembered events")
    return sizes, hand, in_play


class _Collector:
    """The forward pass: applies each remembered event's facts to the anchor."""

    def __init__(
        self, sizes: list[int], hand: set[Card], in_play: list[bool], observer: Seat | None
    ):
        self.observer = observer
        self.at_anchor = in_play
        self.in_play = in_play.copy()
        self.moved: list[Seat | None] = [None] * NUM_CARDS
        dealt = seat_mask([seat for seat in SEATS if sizes[seat] > 0])
        self.allowed = [
            0
            if not in_play[card]
            else 1 << observer
            if observer is not None and card in hand
            else dealt & ~(1 << observer)
            if observer is not None
            else dealt
            for card in CARDS
        ]
        self.at_least_one: dict[tuple[Seat, SetId], tuple[Card, ...]] = {}

    def held(self, card: Card, seat: Seat) -> None:
        """``seat`` held ``card`` at this point."""
        if self.moved[card] is None:
            self.allowed[card] &= 1 << seat
        elif self.moved[card] != seat:
            raise HistoryError(f"card {card} is with seat {self.moved[card]}, not seat {seat}")

    def not_held(self, card: Card, seat: Seat) -> None:
        """``seat`` did not hold ``card`` at this point."""
        if self.moved[card] is None:
            self.allowed[card] &= ~(1 << seat)
        elif self.moved[card] == seat:
            raise HistoryError(f"card {card} is with seat {seat}")

    def ask(self, event: AskEvent) -> None:
        asker, target, card = event.asker, event.target, event.card
        self.not_held(card, asker)
        if event.success:
            self.held(card, target)
        else:
            self.not_held(card, target)
        set_id = set_of(card)
        same_set = set_cards(set_id)
        # The asker held another card of the set. Nothing is learned if the observer is the
        # asker (its hand is known) or a card the asker is known to hold now is in the set.
        # Otherwise it was a card of the set that has not moved since the anchor: still in
        # play then and now, so the asker's holding is fixed since the anchor. Those cards
        # only ever leave this pool, so each later constraint for this seat and set is a
        # subset of the earlier one and implies it: keeping the latest loses nothing.
        if asker != self.observer and not any(self.moved[c] == asker for c in same_set):
            unmoved = tuple(c for c in same_set if self.in_play[c] and self.moved[c] is None)
            self.at_least_one[asker, set_id] = unmoved
        if event.success:
            self.moved[card] = asker

    def call(self, event: CallEvent) -> None:
        for card, holder in zip(set_cards(event.set_id), event.holders, strict=True):
            self.held(card, holder)
            self.moved[card] = None
            self.in_play[card] = False

    def finish(self, start: int, sizes: list[int]) -> Constraints:
        if any(self.allowed[card] == 0 for card in CARDS if self.at_anchor[card]):
            raise HistoryError("no seat can have held some card")
        kept: list[AtLeastOne] = []
        for (seat, _), cards in sorted(self.at_least_one.items()):
            possible = tuple(c for c in cards if self.allowed[c] >> seat & 1)
            if not possible:
                raise HistoryError(f"seat {seat} asked in a set it cannot hold a card of")
            if any(self.allowed[c] == 1 << seat for c in possible):
                continue  # already certain: the seat is known to hold one of them
            kept.append(AtLeastOne(seat, possible))
        return Constraints(
            observer=self.observer,
            start=start,
            sizes=tuple(sizes),
            allowed=tuple(self.allowed),
            at_least_one=tuple(kept),
            moved=tuple(self.moved),
            in_play=tuple(self.in_play),
        )


def constraints(view: PlayerView, events: Sequence[Event], *, use_hand: bool = True) -> Constraints:
    """What ``view.seat`` knows about the deal at the anchor, from ``view`` and ``events``,
    the events it remembers: one unbroken run ending at ``view.last_event``, or empty. With
    ``use_hand`` False the seat's own hand is not used, which gives the public view (RQ2:
    the deals anyone could consider). Raises ``HistoryError`` if the events do not fit."""
    observer = view.seat if use_hand else None
    start = _check_run(view, events)
    sizes, hand, in_play = _anchor(view, events, observer, start)
    collector = _Collector(sizes, hand, in_play, observer)
    for event in events:
        if isinstance(event, AskEvent):
            collector.ask(event)
        elif isinstance(event, CallEvent):
            collector.call(event)
    return collector.finish(start, sizes)
