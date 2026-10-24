"""The per-player projection: exactly what one seat may know (Canonical Ruleset R.2; T2.4).

``project(state, seat, last_event)`` is the only way a player, human or agent, sees a game.
The website sends it to each client and the environment builds each agent's observation from
it (Plan §3), so the two cannot disagree about what is hidden.

A view holds:

- the seat's own hand, and nobody else's (R.2.1);
- every hand size, which sets have been scored and by which team, and so the score (R.2.2);
- the most recent event only: an ask and its answer, a call and its result with the true
  holders of its six cards, or an after-call choice (R.2.2, R.2.3). Earlier events are not
  repeated; remembering them is the player's business (R.2.5; the agent memory wrapper, T2.8);
- the phase, whose turn it is, and during a call's assignment the caller and the set, which
  are shown to everyone (R.8.3);
- during an after-call choice, which team chooses, who may be chosen, the caller if the
  caller chooses, and this seat's own vote, never anyone else's (R.5.2);
- whether a declaration window is open and this seat's own answer in it, never anyone
  else's: who declared and which set stay hidden, and discarded declarations are never shown
  (R.4.3, R.8.3);
- the outcome once the game is over;
- the indices of the actions this seat may take now (``fish_rules.action_index``).

It never holds the game seed (which would reveal the deal), other hands, other seats'
declarations or votes, a window's priority order, or any LOG_ONLY record.

The most recent event is passed in rather than read from the state, so ``State`` and its
hash stay unchanged; ``latest_event`` keeps track of it from the records ``apply`` returns.

``view_to_data`` writes a view as plain JSON data, named ``fish-view-v1``: what the server
sends each client (T3.1) and the client renders (T3.4). Its layout is in docs/determinism.md
§10 and frozen with vectors.
"""

from collections.abc import Iterable
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Final

from fish_rules.action_index import legal_indices
from fish_rules.cards import Hand, Seat, SetId, Team, check_seat, team_seats
from fish_rules.events import AskEvent, CallEvent, ChoiceEvent, Event, Record
from fish_rules.state import Outcome, Phase, State


@dataclass(frozen=True, slots=True)
class PublicCall:
    """R.8.3: the call being assigned. Everyone sees who is calling and which set."""

    caller: Seat
    set_id: SetId


@dataclass(frozen=True, slots=True)
class PublicChoice:
    """R.5.1, R.5.2: the after-call choice in progress.

    ``team`` scored the set and chooses among ``candidates``, its players holding cards.
    ``chooser`` is the caller when the caller's team chooses, otherwise None (the team votes).
    ``own_vote`` is this seat's vote if it is a member of a voting team and has voted, else
    None; other members' votes are never shown.
    """

    team: Team
    candidates: tuple[Seat, ...]
    chooser: Seat | None
    own_vote: Seat | None


@dataclass(frozen=True, slots=True)
class PlayerView:
    """What ``seat`` may know now. See the module docstring for what is and is not included."""

    seat: Seat
    hand: Hand
    hand_sizes: tuple[int, ...]
    scored_by: tuple[Team | None, ...]
    phase: Phase
    current: Seat | None
    call: PublicCall | None
    choice: PublicChoice | None
    window_open: bool
    own_declaration: SetId | None
    responded: bool
    last_event: Event | None
    outcome: Outcome | None
    winner: Team | None
    legal: tuple[int, ...]

    def score(self, team: Team) -> int:
        """R.2.2: the number of sets ``team`` has scored."""
        return sum(1 for scorer in self.scored_by if scorer == team)


def latest_event(records: Iterable[Record], previous: Event | None) -> Event | None:
    """The most recent event after ``records``: the last ask, call or after-call choice among
    them, or ``previous`` if they hold none (R.2.2)."""
    latest = previous
    for record in records:
        if isinstance(record, AskEvent | CallEvent | ChoiceEvent):
            latest = record
    return latest


def _check_last_event(state: State, last_event: Event | None) -> None:
    """``last_event`` must be the state's most recent event: None before the first event,
    else the event numbered ``state.events - 1``."""
    if last_event is None:
        if state.events:
            raise ValueError(f"the game has had {state.events} events; pass the most recent")
        return
    if last_event.number != state.events - 1:
        raise ValueError(
            f"event {last_event.number} is not the most recent; the game has had "
            f"{state.events} events"
        )


def _choice(state: State, seat: Seat) -> PublicChoice | None:
    choice = state.choice
    if choice is None:
        return None
    members = team_seats(choice.team)
    own_vote = choice.votes[members.index(seat)] if seat in members else None
    return PublicChoice(choice.team, choice.candidates, choice.chooser, own_vote)


def project(state: State, seat: Seat, last_event: Event | None) -> PlayerView:
    """What ``seat`` may know of ``state``, given ``last_event``, the game's most recent event
    (None before the first). Raises ValueError if ``last_event`` is not that event."""
    check_seat(seat)
    _check_last_event(state, last_event)
    window = state.window
    call = state.call
    winner = state.winner() if state.outcome is Outcome.FINISHED else None
    return PlayerView(
        seat=seat,
        hand=state.hands[seat],
        hand_sizes=tuple(len(hand) for hand in state.hands),
        scored_by=state.scored_by,
        phase=state.phase,
        current=state.current,
        call=None if call is None else PublicCall(call.caller, call.set_id),
        choice=_choice(state, seat),
        window_open=window is not None,
        own_declaration=None if window is None else window.declared[seat],
        responded=window is not None and window.responded[seat],
        last_event=last_event,
        outcome=state.outcome,
        winner=winner,
        legal=legal_indices(state, seat),
    )


# ---------------------------------------------------------------- as data (fish-view-v1)

VIEW_ENCODING: Final = "fish-view-v1"
"""Names the layout ``view_to_data`` writes. A different layout needs a new name."""


def _plain(value: object) -> object:
    """``value`` as JSON data: enums as their strings, tuples as lists."""
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, tuple):
        items: tuple[object, ...] = value  # pyright: ignore[reportUnknownVariableType]
        return [_plain(item) for item in items]
    return value


def event_to_data(event: Event) -> dict[str, object]:
    """``event`` as ``{"type": <class name>, <field>: <value>, ...}``, every value an int, a
    bool, a string, None or a list of ints."""
    data: dict[str, object] = {"type": type(event).__name__}
    for field in fields(event):
        data[field.name] = _plain(getattr(event, field.name))
    return data


def view_to_data(view: PlayerView) -> dict[str, object]:
    """``view`` as plain data, ready for JSON (``fish-view-v1``). ``window`` is None unless a
    window is open; ``call``, ``choice`` and ``last_event`` are None when there is none."""
    call = view.call
    choice = view.choice
    return {
        "encoding": VIEW_ENCODING,
        "seat": view.seat,
        "hand": list(view.hand),
        "hand_sizes": list(view.hand_sizes),
        "scored_by": list(view.scored_by),
        "phase": str(view.phase),
        "current": view.current,
        "call": None if call is None else {"caller": call.caller, "set_id": call.set_id},
        "choice": None
        if choice is None
        else {
            "team": choice.team,
            "candidates": list(choice.candidates),
            "chooser": choice.chooser,
            "own_vote": choice.own_vote,
        },
        "window": {"own_declaration": view.own_declaration, "responded": view.responded}
        if view.window_open
        else None,
        "last_event": None if view.last_event is None else event_to_data(view.last_event),
        "outcome": None if view.outcome is None else str(view.outcome),
        "winner": view.winner,
        "legal": list(view.legal),
    }
