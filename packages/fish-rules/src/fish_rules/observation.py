"""Agent observations: a seat's view as a fixed-length vector of bits (T2.4).

``encode(view)`` turns a ``fish_rules.view.PlayerView`` into ``OBS_SIZE`` bytes, each 0 or
1, so an agent sees exactly what the projection allows and nothing more (R.2). It lives in
fish-rules, beside the action layout, so the environment, the baselines and the website's
bots (T3.5) all encode views the same way without NumPy.

Seats are written relative to the observing seat, matching the action layout
(``fish_rules.action_index``): seat slots 0, 1, 2 are the seat's own team in ascending order
(itself included, at the slot ``me`` marks), and slots 3, 4, 5 are the opponents in ascending
order. "Mine" and "theirs" are the observing seat's team and the other team.

The layout is ``OBS_LAYOUT``: named blocks, in order, each a run of bits. A block is either
flags or one-hot (at most one bit set; none set means "none" or "not applicable"). Hand sizes
are one-hot over 0 to 54 cards per seat. The layout is named ``fish-obs-v1``, documented in
docs/determinism.md §11 and frozen with vectors; a different layout needs a new name.
"""

from typing import Final

from fish_rules.action_index import opponents, teammates
from fish_rules.cards import CARDS_PER_SET, NUM_CARDS, NUM_SEATS, NUM_SETS, Seat, Team, team_of
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent
from fish_rules.state import CallSource, Outcome, Phase
from fish_rules.view import PlayerView

OBS_ENCODING: Final = "fish-obs-v1"
"""Names this layout."""

PHASES: Final[tuple[Phase, ...]] = (
    Phase.TURN, Phase.WINDOW, Phase.ASSIGN, Phase.CHOOSE, Phase.VOTE, Phase.RUNOUT, Phase.OVER,
)  # fmt: skip
SOURCES: Final[tuple[CallSource, ...]] = (CallSource.WINDOW, CallSource.TURN, CallSource.RUNOUT)
HAND_SIZE_VALUES: Final = NUM_CARDS + 1
"""A hand holds 0 to 54 cards."""

OBS_LAYOUT: Final[tuple[tuple[str, int], ...]] = (
    ("hand", NUM_CARDS),  # own cards, by card number
    ("me", 3),  # which own-team slot is this seat
    ("hand_sizes", NUM_SEATS * HAND_SIZE_VALUES),  # per seat slot, one-hot 0..54
    ("sets", NUM_SETS * 3),  # per set, one-hot: in play, scored by mine, scored by theirs
    ("phase", len(PHASES)),  # one-hot, in PHASES order
    ("current", NUM_SEATS),  # seat slot whose turn it is; none once over
    ("call_caller", NUM_SEATS),  # the call being assigned: caller's seat slot
    ("call_set", NUM_SETS),  # and its set
    ("choice_team", 2),  # after-call choice: mine, theirs
    ("choice_candidates", NUM_SEATS),  # flags: seat slots that may be chosen
    ("choice_chooser", NUM_SEATS),  # the caller when the caller chooses; none in a vote
    ("own_vote", NUM_SEATS),  # this seat's vote, if cast
    ("own_declaration", NUM_SETS),  # this seat's declaration in the open window
    ("responded", 1),  # this seat has answered the open window
    ("event", 3),  # most recent event: ask, call, choice; none before the first
    ("ask_asker", NUM_SEATS),
    ("ask_target", NUM_SEATS),
    ("ask_card", NUM_CARDS),
    ("ask_success", 1),
    ("call_event_caller", NUM_SEATS),
    ("call_event_set", NUM_SETS),
    ("call_event_source", len(SOURCES)),  # one-hot, in SOURCES order
    ("call_event_assignment", CARDS_PER_SET * NUM_SEATS),  # per card: assigned seat slot
    ("call_event_timed_out", 1),  # no assignment: the caller ran out of time (website only)
    ("call_event_holders", CARDS_PER_SET * NUM_SEATS),  # per card: true holder's slot (R.2.3)
    ("call_event_correct", 1),
    ("call_event_scored_by", 2),  # mine, theirs
    ("choice_event_team", 2),  # mine, theirs
    ("choice_event_seat", NUM_SEATS),
    ("outcome", 2),  # finished, unfinished
    ("winner", 2),  # mine, theirs
)
"""Every block of ``fish-obs-v1``, in order, with its width in bits."""


def _offsets() -> dict[str, int]:
    offsets: dict[str, int] = {}
    at = 0
    for name, width in OBS_LAYOUT:
        offsets[name] = at
        at += width
    return offsets


OFFSETS: Final[dict[str, int]] = _offsets()
"""Where each block of ``OBS_LAYOUT`` starts."""

OBS_SIZE: Final = sum(width for _, width in OBS_LAYOUT)
"""648: the length of an observation."""


def seat_slots(seat: Seat) -> tuple[Seat, ...]:
    """The seat in each slot, from ``seat``'s point of view: its team ascending, then the
    opponents ascending."""
    return (*teammates(seat), *opponents(seat))


def encode(view: PlayerView) -> bytes:
    """``view`` as ``OBS_SIZE`` bytes, each 0 or 1 (``fish-obs-v1``)."""
    bits = bytearray(OBS_SIZE)
    slot = {s: i for i, s in enumerate(seat_slots(view.seat))}
    mine = team_of(view.seat)

    def put(block: str, index: int) -> None:
        bits[OFFSETS[block] + index] = 1

    def side(team: Team) -> int:
        return 0 if team == mine else 1

    for card in view.hand:
        put("hand", card)
    put("me", slot[view.seat])
    for s, size in enumerate(view.hand_sizes):
        put("hand_sizes", slot[s] * HAND_SIZE_VALUES + size)
    for set_id, scorer in enumerate(view.scored_by):
        put("sets", set_id * 3 + (0 if scorer is None else 1 + side(scorer)))
    put("phase", PHASES.index(view.phase))
    if view.current is not None:
        put("current", slot[view.current])
    if view.call is not None:
        put("call_caller", slot[view.call.caller])
        put("call_set", view.call.set_id)
    if view.choice is not None:
        put("choice_team", side(view.choice.team))
        for candidate in view.choice.candidates:
            put("choice_candidates", slot[candidate])
        if view.choice.chooser is not None:
            put("choice_chooser", slot[view.choice.chooser])
        if view.choice.own_vote is not None:
            put("own_vote", slot[view.choice.own_vote])
    if view.own_declaration is not None:
        put("own_declaration", view.own_declaration)
    if view.responded:
        put("responded", 0)
    event = view.last_event
    if isinstance(event, AskEvent):
        put("event", 0)
        put("ask_asker", slot[event.asker])
        put("ask_target", slot[event.target])
        put("ask_card", event.card)
        if event.success:
            put("ask_success", 0)
    elif isinstance(event, CallEvent):
        put("event", 1)
        put("call_event_caller", slot[event.caller])
        put("call_event_set", event.set_id)
        put("call_event_source", SOURCES.index(event.source))
        if event.assignment is None:
            put("call_event_timed_out", 0)
        else:
            for i, holder in enumerate(event.assignment):
                put("call_event_assignment", i * NUM_SEATS + slot[holder])
        for i, holder in enumerate(event.holders):
            put("call_event_holders", i * NUM_SEATS + slot[holder])
        if event.correct:
            put("call_event_correct", 0)
        put("call_event_scored_by", side(event.scored_by))
    elif isinstance(event, ChoiceEvent):
        put("event", 2)
        put("choice_event_team", side(event.team))
        put("choice_event_seat", slot[event.seat])
    if view.outcome is not None:
        put("outcome", 0 if view.outcome is Outcome.FINISHED else 1)
    if view.winner is not None:
        put("winner", side(view.winner))
    return bytes(bits)
