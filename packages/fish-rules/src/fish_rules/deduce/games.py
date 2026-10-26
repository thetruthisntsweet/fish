"""Layer 1 over a recorded game, for analysis (T2.7; RQ1, RQ2).

A recorded game is its starting state and its actions (``fish_rules.record``,
``fish_rules.corpus``), so what any seat knew at any moment can be worked out afterwards:

- ``knowledge`` gives a seat's deduction (or the public one) at the deal and after every
  event: the decision points at which beliefs are scored (T1.1 §1). A call and the
  after-call choice it leads to can come from one action (a choice the game seed makes);
  then there is one decision point, after both;
- ``certain_misses`` finds the asks whose asker could have deduced, from what it had seen,
  that the target did not hold the card, so the ask was sure to give up the turn (RQ2 §3.2).

Both take ``remembered``: None for perfect memory, or a number of most recent events, so the
same questions can be asked of a seat that remembers only the last few (or, with 0, only
what is on screen: the latest event, the hand sizes, the scored sets and its own hand).
"""

from collections.abc import Iterator, Sequence

from fish_rules.cards import Seat
from fish_rules.deduce.solve import Deduction, deduce
from fish_rules.engine import apply
from fish_rules.events import Action, Ask, AskEvent, CallEvent, ChoiceEvent, Event
from fish_rules.state import State
from fish_rules.view import latest_event, project


def _recent(events: Sequence[Event], remembered: int | None) -> Sequence[Event]:
    if remembered is None:
        return events
    return events[-remembered:] if remembered else ()


def knowledge(
    start: State,
    actions: Sequence[Action],
    seat: Seat | None,
    *,
    remembered: int | None = None,
) -> Iterator[Deduction]:
    """``seat``'s deduction at ``start`` and after each action among ``actions`` that produces
    an event; with ``seat`` None, the public view's. ``start`` is normally
    ``new_game(seed)``."""
    state, last = start, None
    events: list[Event] = []

    def now() -> Deduction:
        view = project(state, 0 if seat is None else seat, last)
        return deduce(view, _recent(events, remembered), use_hand=seat is not None)

    yield now()
    for action in actions:
        state, records = apply(state, action)
        last = latest_event(records, last)
        produced = [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
        if produced:
            events += produced
            yield now()


def certain_misses(
    start: State, actions: Sequence[Action], *, remembered: int | None = None
) -> tuple[AskEvent, ...]:
    """The asks among ``actions`` whose asker could have deduced, from its view just before
    and the events it remembered, that the target did not hold the card. Each is a miss."""
    state, last = start, None
    events: list[Event] = []
    found: list[AskEvent] = []
    for action in actions:
        certain = False
        if isinstance(action, Ask):
            view = project(state, action.seat, last)
            deduction = deduce(view, _recent(events, remembered))
            certain = not deduction.holders[action.card] >> action.target & 1
        state, records = apply(state, action)
        last = latest_event(records, last)
        produced = [r for r in records if isinstance(r, AskEvent | CallEvent | ChoiceEvent)]
        if certain:
            found.append(next(r for r in produced if isinstance(r, AskEvent)))
        events += produced
    return tuple(found)
