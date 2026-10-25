"""The corpus record, ``fish-corpus-v1`` (docs/corpus.md §4 to §7).

One website game as plain data, ready for JSON: the game record of ``fish_rules.record``
(ruleset, action encoding, seed, outcome, winner, actions), so ``replay_record`` replays it,
plus:

- ``corpus``: ``"fish-corpus-v1"``;
- ``game``: ``id``, ``month`` (``YYYY-MM``), ``completion``, ``matchmaking``,
  ``cohort_table``, ``server_commit``, ``protocol_version`` (§3);
- ``seats``: six entries, seat 0 first, each ``person``, ``cohort``, ``agent``, ``memory``,
  ``k`` and ``note`` (§4): a person has a pseudonym, a cohort flag, memory ``human`` and a
  note answer; a bot has an agent version and a memory setting (``k`` for ``last-k``);
- ``times``: per action ``[received_us, sent_us]``, microseconds since the game started
  (§5.1);
- ``causes``: per action ``{"seat": s}`` or ``{"timer": t}`` (§5.1);
- ``log``: server log rows, each with ``type``, ``after`` (actions applied so far) and
  ``at_us`` (§5.2).

``read_corpus_record`` checks every field and replays the game, so a record that reads is
one the rules allow. ``corpus_record`` writes a record and reads it back, so a writer cannot
produce one that does not read. ``response_times`` and ``analysis_flags`` are the one
definition of response time (§5.3) and of the analysis sets that a record decides on its own
(§6); membership also needs consent, which only the server holds.

Website mechanics only (R.8.3): a Call press is recorded as ``OpenWindow`` (when no window
is open) followed by the presser's ``Declare`` at the same received time, windows close by
the window timer, and nobody passes.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from fish_rules.cards import NUM_SEATS, SEATS, Seat
from fish_rules.codec import action_from_data
from fish_rules.engine import acting_seats, apply
from fish_rules.events import (
    Action,
    AskEvent,
    AssignTimeout,
    CallEvent,
    ChoiceEvent,
    ChoiceTimeout,
    CloseWindow,
    Declare,
    OpenWindow,
    Pass,
)
from fish_rules.record import game_record, replay_record
from fish_rules.state import Outcome, State, new_game

CORPUS_ENCODING: Final = "fish-corpus-v1"
"""Names this record format. A change of shape or meaning needs a new name."""

COMPLETIONS: Final = ("finished", "unfinished", "abandoned")
MATCHMAKING: Final = ("solo", "group")
BOT_MEMORY: Final = ("full", "last-k", "none")
NOTE_ANSWERS: Final = ("yes", "no", "declined", "unanswered")
TIMERS: Final = ("window", "assignment", "choice")
REJECT_REASONS: Final = ("illegal", "stale", "malformed")
CONNECTION_STATES: Final = ("connected", "disconnected", "reconnected")
HANDOVER_REASONS: Final = ("turn_timeout", "disconnect")

_GAME_KEYS: Final = frozenset(
    {"id", "month", "completion", "matchmaking", "cohort_table", "server_commit",
     "protocol_version"}
)  # fmt: skip
_SEAT_KEYS: Final = frozenset({"person", "cohort", "agent", "memory", "k", "note"})
_LOG_KEYS: Final[dict[str, frozenset[str]]] = {
    "rtt": frozenset({"seat", "rtt_us"}),
    "rejected": frozenset({"seat", "input", "reason"}),
    "bot_delay": frozenset({"seat", "delay_us", "dropped"}),
    "connection": frozenset({"seat", "state"}),
    "handover": frozenset({"seat", "reason", "agent", "memory", "k"}),
}
_MONTH: Final = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_NAME_LENGTH: Final = 64


class CorpusError(ValueError):
    """A corpus record is malformed or does not describe a game the rules allow."""


# ---------------------------------------------------------------- parsed records


@dataclass(frozen=True)
class GameInfo:
    """The game-level fields (§3)."""

    id: str
    month: str
    completion: str
    matchmaking: str
    cohort_table: bool
    server_commit: str
    protocol_version: int


@dataclass(frozen=True)
class SeatInfo:
    """Who held a seat at the start (§4). Exactly one of ``person`` and ``agent`` is set."""

    person: str | None
    cohort: bool | None
    agent: str | None
    memory: str
    k: int | None
    note: str | None


@dataclass(frozen=True)
class Step:
    """One action and how it reached the engine (§5.1)."""

    action: Action
    seat: Seat | None
    timer: str | None
    received_us: int
    sent_us: int


@dataclass(frozen=True)
class LogRow:
    """One server log row (§5.2). ``fields`` holds the type's own keys besides ``seat``."""

    type: str
    after: int
    at_us: int
    seat: Seat
    fields: Mapping[str, object]


@dataclass(frozen=True)
class CorpusGame:
    """A corpus record that has been checked and replayed."""

    seed: int
    game: GameInfo
    seats: tuple[SeatInfo, ...]
    steps: tuple[Step, ...]
    log: tuple[LogRow, ...]
    final: State

    def handover_after(self, seat: Seat) -> int | None:
        """The number of actions applied when ``seat`` was handed to a bot, if it was."""
        for row in self.log:
            if row.type == "handover" and row.seat == seat:
                return row.after
        return None

    def person_acts(self, seat: Seat, index: int) -> bool:
        """Whether a person held ``seat`` when action ``index`` was applied (§4.1)."""
        if self.seats[seat].person is None:
            return False
        after = self.handover_after(seat)
        return after is None or index < after


@dataclass(frozen=True)
class AnalysisFlags:
    """What the record alone decides about the analysis sets (§6). Membership also needs every
    person's consent and age, held by the server."""

    completed: bool
    finished: bool
    solo: bool
    bot_seat: bool
    note_yes: bool
    note_missing: bool
    all_cohort: bool
    mixed_cohort: bool

    @property
    def primary(self) -> bool:
        """Finished, solo, no bot at any point, nobody answered yes to the note question."""
        return self.finished and self.solo and not self.bot_seat and not self.note_yes


# ---------------------------------------------------------------- field readers


def _mapping(value: object, what: str, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CorpusError(f"{what} is an object, got {value!r}")
    data = cast(Mapping[str, object], value)
    if frozenset(data) != keys:
        raise CorpusError(f"{what} has keys {sorted(data)}; expected {sorted(keys)}")
    return data


def _get(value: object, key: str) -> object:
    """``value[key]`` if ``value`` is an object with that key, else None."""
    return cast(Mapping[str, object], value).get(key) if isinstance(value, dict) else None


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise CorpusError(f"{what} is a list, got {value!r}")
    return cast(list[object], value)


def _int(value: object, what: str, low: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise CorpusError(f"{what} is an integer of at least {low}, got {value!r}")
    return value


def _bool(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise CorpusError(f"{what} is true or false, got {value!r}")
    return value


def _name(value: object, what: str) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= _NAME_LENGTH:
        raise CorpusError(f"{what} is a string of 1 to {_NAME_LENGTH} characters, got {value!r}")
    return value


def _choice(value: object, what: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise CorpusError(f"{what} is one of {allowed}, got {value!r}")
    return cast(str, value)


def _seat(value: object, what: str) -> Seat:
    if isinstance(value, bool) or not isinstance(value, int) or value not in SEATS:
        raise CorpusError(f"{what} is a seat 0-5, got {value!r}")
    return value


def _bot_memory(memory: object, k: object, what: str) -> tuple[str, int | None]:
    memory = _choice(memory, f"{what} memory", BOT_MEMORY)
    if memory == "last-k":
        return memory, _int(k, f"{what} k", low=1)
    if k is not None:
        raise CorpusError(f"{what} has k only with memory last-k, got {k!r}")
    return memory, None


def _game_info(value: object, outcome: Outcome | None) -> GameInfo:
    data = _mapping(value, "game", _GAME_KEYS)
    month = data["month"]
    if not isinstance(month, str) or _MONTH.fullmatch(month) is None:
        raise CorpusError(f"game month is YYYY-MM, got {month!r}")
    completion = _choice(data["completion"], "game completion", COMPLETIONS)
    expected = "abandoned" if outcome is None else str(outcome)
    if completion != expected:
        raise CorpusError(f"game completion is {completion!r}, but the replay is {expected!r}")
    return GameInfo(
        id=_name(data["id"], "game id"),
        month=month,
        completion=completion,
        matchmaking=_choice(data["matchmaking"], "game matchmaking", MATCHMAKING),
        cohort_table=_bool(data["cohort_table"], "game cohort_table"),
        server_commit=_name(data["server_commit"], "game server_commit"),
        protocol_version=_int(data["protocol_version"], "game protocol_version", low=1),
    )


def _seat_info(value: object, seat: Seat) -> SeatInfo:
    what = f"seat {seat}"
    data = _mapping(value, what, _SEAT_KEYS)
    if data["person"] is not None:
        if data["agent"] is not None or data["memory"] != "human" or data["k"] is not None:
            raise CorpusError(f"{what} is a person: no agent, memory human, no k")
        return SeatInfo(
            person=_name(data["person"], f"{what} person"),
            cohort=_bool(data["cohort"], f"{what} cohort"),
            agent=None,
            memory="human",
            k=None,
            note=_choice(data["note"], f"{what} note", NOTE_ANSWERS),
        )
    if data["cohort"] is not None or data["note"] is not None:
        raise CorpusError(f"{what} is a bot: no cohort, no note")
    memory, k = _bot_memory(data["memory"], data["k"], what)
    return SeatInfo(
        person=None,
        cohort=None,
        agent=_name(data["agent"], f"{what} agent"),
        memory=memory,
        k=k,
        note=None,
    )


def _seats(value: object, cohort_table: bool) -> tuple[SeatInfo, ...]:
    items = _list(value, "seats")
    if len(items) != NUM_SEATS:
        raise CorpusError(f"seats has {NUM_SEATS} entries, got {len(items)}")
    seats = tuple(_seat_info(item, seat) for seat, item in zip(SEATS, items, strict=True))
    people = [s.person for s in seats if s.person is not None]
    if not people:
        raise CorpusError("a website game has at least one person")
    if len(set(people)) != len(people):
        raise CorpusError("a person holds at most one seat")
    if cohort_table and not all(s.cohort for s in seats if s.person is not None):
        raise CorpusError("a cohort table seats only cohort players")
    return seats


def _steps(actions: Sequence[Action], times: object, causes: object) -> tuple[Step, ...]:
    time_items, cause_items = _list(times, "times"), _list(causes, "causes")
    if not len(time_items) == len(cause_items) == len(actions):
        raise CorpusError("times and causes have one entry per action")
    steps: list[Step] = []
    for n, (action, pair, cause) in enumerate(zip(actions, time_items, cause_items, strict=True)):
        stamp = _list(pair, f"times[{n}]")
        if len(stamp) != 2:
            raise CorpusError(f"times[{n}] is [received_us, sent_us]")
        received, sent = _int(stamp[0], f"times[{n}] received"), _int(stamp[1], f"times[{n}] sent")
        if sent < received or (
            steps and (received < steps[-1].received_us or sent < steps[-1].sent_us)
        ):
            raise CorpusError(f"times[{n}]: sent after received, both never going back")
        seat, timer = _cause(cause, f"causes[{n}]")
        steps.append(Step(action, seat, timer, received, sent))
    return tuple(steps)


def _cause(value: object, what: str) -> tuple[Seat | None, str | None]:
    """A cause is ``{"seat": s}`` or ``{"timer": t}``."""
    if _get(value, "timer") is not None:
        data = _mapping(value, what, frozenset({"timer"}))
        return None, _choice(data["timer"], f"{what} timer", TIMERS)
    data = _mapping(value, what, frozenset({"seat"}))
    return _seat(data["seat"], f"{what} seat"), None


_TIMER_OF: Final[dict[type, str]] = {
    CloseWindow: "window",
    AssignTimeout: "assignment",
    ChoiceTimeout: "choice",
}


def _check_causes(steps: Sequence[Step]) -> None:
    """Website mechanics (R.8.3): presses open windows, timers close them and end timeouts."""
    for n, step in enumerate(steps):
        action = step.action
        timer = _TIMER_OF.get(type(action))
        if timer is not None:
            if step.timer != timer:
                raise CorpusError(
                    f"action {n} ({type(action).__name__}) is caused by the {timer} timer"
                )
        elif isinstance(action, Pass):
            raise CorpusError(f"action {n}: nobody passes on the website")
        elif isinstance(action, OpenWindow):
            following = steps[n + 1] if n + 1 < len(steps) else None
            if (
                step.seat is None
                or following is None
                or not isinstance(following.action, Declare)
                or following.action.seat != step.seat
                or following.seat != step.seat
                or following.received_us != step.received_us
            ):
                raise CorpusError(
                    f"action {n}: a window opens with a press, then the presser's Declare"
                )
        elif step.seat != cast(Declare, action).seat:  # every other action has a seat
            raise CorpusError(f"action {n} is caused by its own seat")


def _log(value: object, steps: Sequence[Step], seats: Sequence[SeatInfo]) -> tuple[LogRow, ...]:
    rows: list[LogRow] = []
    handed: dict[Seat, int] = {}
    for i, item in enumerate(_list(value, "log")):
        what = f"log[{i}]"
        kind = _choice(_get(item, "type"), f"{what} type", tuple(_LOG_KEYS))
        data = _mapping(item, what, _LOG_KEYS[kind] | {"type", "after", "at_us"})
        after = _int(data["after"], f"{what} after")
        at_us = _int(data["at_us"], f"{what} at_us")
        seat = _seat(data["seat"], f"{what} seat")
        if after > len(steps) or (rows and (after < rows[-1].after or at_us < rows[-1].at_us)):
            raise CorpusError(f"{what}: after and at_us never go back, after at most the actions")
        person = seats[seat].person is not None and (seat not in handed or after < handed[seat])
        match kind:
            case "rtt":
                _int(data["rtt_us"], f"{what} rtt_us")
            case "rejected":
                _choice(data["reason"], f"{what} reason", REJECT_REASONS)
            case "bot_delay":
                _int(data["delay_us"], f"{what} delay_us")
                _bool(data["dropped"], f"{what} dropped")
            case "connection":
                _choice(data["state"], f"{what} state", CONNECTION_STATES)
            case _:
                _choice(data["reason"], f"{what} reason", HANDOVER_REASONS)
                _name(data["agent"], f"{what} agent")
                _bot_memory(data["memory"], data["k"], what)
                if not person:
                    raise CorpusError(f"{what}: only a person's seat is handed to a bot (R.8.4)")
                handed[seat] = after
        if kind == "rtt" and not person:
            raise CorpusError(f"{what}: rtt rows are for a seat a person holds")
        if kind == "connection" and seats[seat].person is None:
            raise CorpusError(f"{what}: connection rows are for a person's seat")
        if kind == "bot_delay" and person:
            raise CorpusError(f"{what}: bot_delay rows are for a seat a bot holds")
        fields = {k: v for k, v in data.items() if k not in ("type", "after", "at_us", "seat")}
        rows.append(LogRow(kind, after, at_us, seat, fields))
    return tuple(rows)


# ---------------------------------------------------------------- reading and writing


def read_corpus_record(data: Mapping[str, object]) -> CorpusGame:
    """Check ``data`` and replay it. Raises ``CorpusError`` (a ValueError) if any field is
    malformed, the times or causes do not fit the actions, or a log row does not fit the seats;
    ``replay_record``'s errors (wrong versions, an illegal action, a wrong outcome) are
    ValueErrors too."""
    final = replay_record(data)
    if data.get("corpus") != CORPUS_ENCODING:
        raise CorpusError(f"corpus is {CORPUS_ENCODING!r}, got {data.get('corpus')!r}")
    game = _game_info(data.get("game"), final.outcome)
    seats = _seats(data.get("seats"), game.cohort_table)
    actions = tuple(
        action_from_data(cast(Mapping[str, object], a)) for a in _list(data["actions"], "actions")
    )
    steps = _steps(actions, data.get("times"), data.get("causes"))
    _check_causes(steps)
    log = _log(data.get("log"), steps, seats)
    return CorpusGame(int(cast(str, data["seed"])), game, seats, steps, log, final)


def corpus_record(
    seed: int,
    actions: Sequence[Action],
    state: State,
    *,
    game: Mapping[str, object],
    seats: Sequence[Mapping[str, object]],
    times: Iterable[tuple[int, int]],
    causes: Iterable[Mapping[str, object]],
    log: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """The corpus record of the game ``actions`` played from ``seed``, now in ``state``. Read
    back before it is returned, so it raises ``CorpusError`` rather than write a bad record."""
    record = game_record(seed, actions, state)
    record |= {
        "corpus": CORPUS_ENCODING,
        "game": dict(game),
        "seats": [dict(seat) for seat in seats],
        "times": [[received, sent] for received, sent in times],
        "causes": [dict(cause) for cause in causes],
        "log": [dict(row) for row in log],
    }
    read_corpus_record(record)
    return record


# ---------------------------------------------------------------- derived values


def response_times(game: CorpusGame) -> tuple[int | None, ...]:
    """Per action, a person's response time in microseconds (§5.3), or None for a bot's action,
    a timer and the ``OpenWindow`` of a press (the press's time goes to its ``Declare``).

    A decision point starts when the update was sent after which the seat could act and stayed
    able to act (``acting_seats``) until it did; a press starts at the update that brought the
    most recent numbered event. No call-entry freeze (R.4.3) ever falls inside a decision
    point: only the caller acts during one, and it ends with the call, a numbered event, so
    T1.1's exclusion of the freeze holds without subtracting anything. A value can be negative
    when the input arrived while the update it answers was still being sent.
    """
    state = new_game(game.seed)
    since: dict[Seat, int] = dict.fromkeys(acting_seats(state), 0)
    last_event = 0
    out: list[int | None] = []
    for n, step in enumerate(game.steps):
        action = step.action
        value: int | None = None
        if (
            step.seat is not None
            and game.person_acts(step.seat, n)
            and not isinstance(action, OpenWindow)
        ):
            start = last_event if isinstance(action, Declare) else since[step.seat]
            value = step.received_us - start
        out.append(value)
        state, records = apply(state, action)
        if any(isinstance(r, AskEvent | CallEvent | ChoiceEvent) for r in records):
            last_event = step.sent_us
        acting = acting_seats(state)
        since = {s: since[s] if s in since and s != step.seat else step.sent_us for s in acting}
    return tuple(out)


def analysis_flags(game: CorpusGame) -> AnalysisFlags:
    """The analysis-set flags the record decides (§6)."""
    people = [s for s in game.seats if s.person is not None]
    cohorts = {s.cohort for s in people}
    return AnalysisFlags(
        completed=game.game.completion != "abandoned",
        finished=game.game.completion == "finished",
        solo=game.game.matchmaking == "solo",
        bot_seat=len(people) < NUM_SEATS or any(row.type == "handover" for row in game.log),
        note_yes=any(s.note == "yes" for s in people),
        note_missing=any(s.note in ("declined", "unanswered") for s in people),
        all_cohort=cohorts == {True},
        mixed_cohort=cohorts == {True, False},
    )
