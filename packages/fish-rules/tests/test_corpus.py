"""Tests for fish_rules.corpus: the fish-corpus-v1 record (docs/corpus.md §4 to §7). Records of
random website-mechanics games read back after JSON exactly; response times follow §5.3; the
analysis-set flags follow §6; and every malformed record is rejected."""

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fish_rules.cards import SEATS, Seat
from fish_rules.codec import action_from_data
from fish_rules.corpus import (
    CORPUS_ENCODING,
    CorpusError,
    CorpusGame,
    analysis_flags,
    corpus_record,
    read_corpus_record,
    response_times,
)
from fish_rules.engine import acting_seats, apply, legal_actions, replay
from fish_rules.events import (
    Action,
    Ask,
    CloseWindow,
    Declare,
    OpenWindow,
)
from fish_rules.playout import random_website_game
from fish_rules.record import replay_record
from fish_rules.state import Phase, State, new_game, state_hash

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 10)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games: a tenth of the profile's examples (10 in dev, 100 in CI, 5,000 nightly)."""

GAME: dict[str, object] = {
    "id": "g-0001",
    "month": "2026-12",
    "completion": "finished",
    "matchmaking": "solo",
    "cohort_table": False,
    "server_commit": "abc1234",
    "protocol_version": 1,
}


def person(n: int, *, cohort: bool = False, note: str = "no") -> dict[str, object]:
    return {"person": f"p{n}", "cohort": cohort, "agent": None, "memory": "human", "k": None,
            "note": note}  # fmt: skip


def bot(memory: str = "last-k", k: int | None = 8) -> dict[str, object]:
    return {"person": None, "cohort": None, "agent": "b1-v1", "memory": memory, "k": k,
            "note": None}  # fmt: skip


PEOPLE: list[dict[str, object]] = [person(n) for n in SEATS]


Played = tuple[int, State, list[Action], list[dict[str, object]], list[tuple[int, int]]]


def website_play(game_seed: int, policy_seed: int, max_actions: int = 2_000) -> Played:
    """A random game under website mechanics (``fish_rules.playout.random_website_game``)."""
    actions, causes, times = random_website_game(game_seed, policy_seed, max_actions)
    *_, (state, _) = replay(game_seed, actions)
    return game_seed, state, list(actions), list(causes), list(times)


def completion(state: State) -> str:
    return "abandoned" if state.outcome is None else str(state.outcome)


def record_of(
    played: Played,
    *,
    seats: list[dict[str, object]] | None = None,
    log: list[dict[str, object]] | None = None,
    **game: object,
) -> dict[str, object]:
    seed, state, actions, causes, times = played
    return corpus_record(
        seed,
        actions,
        state,
        game=GAME | {"completion": completion(state)} | game,
        seats=PEOPLE if seats is None else seats,
        times=times,
        causes=causes,
        log=log or [],
    )


# ---------------------------------------------------------------- whole games


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_every_website_game_reads_back_after_json(game_seed: int, policy_seed: int) -> None:
    """A record of any website-mechanics game, written to JSON text and read back, is the same
    game: the same final state, and replay_record still replays it (R.10.2)."""
    played = website_play(game_seed, policy_seed)
    record = json.loads(json.dumps(record_of(played)))
    game = read_corpus_record(record)
    assert state_hash(game.final) == state_hash(played[1]) == state_hash(replay_record(record))
    assert [s.action for s in game.steps] == played[2]


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_response_times_follow_the_definition(game_seed: int, policy_seed: int) -> None:
    """§5.3: a time for every person's seat input except the OpenWindow of a press, none for a
    timer or a bot; a press is timed from the most recent numbered event."""
    played = website_play(game_seed, policy_seed)
    seats = [*PEOPLE[:5], bot("full", None)]
    game = read_corpus_record(record_of(played, seats=seats))
    times = response_times(game)
    assert len(times) == len(game.steps)
    for step, value in zip(game.steps, times, strict=True):
        timed = step.seat is not None and step.seat != 5 and not isinstance(step.action, OpenWindow)
        assert (value is not None) == timed
        if value is not None:
            assert value <= step.received_us


type Entry = tuple[Action, dict[str, object], int, int]


def test_response_times_on_a_small_game() -> None:
    """Exact values: an ask timed from the deal, a press from the most recent event, the
    caller's assignment from the window's close, and nothing for timers."""
    state = new_game(0)
    current = state.current
    assert current is not None
    ask = next(a for a in legal_actions(state, current) if isinstance(a, Ask))
    presser: Seat = (current + 1) % 6  # pyright: ignore[reportAssignmentType]
    steps: list[Entry] = [(ask, {"seat": current}, 2_000, 2_100)]
    state, _ = apply(state, ask)
    set_id = state.sets_in_play()[0]
    window: list[Entry] = [
        (OpenWindow(), {"seat": presser}, 5_000, 5_050),
        (Declare(presser, set_id), {"seat": presser}, 5_000, 5_060),
        (CloseWindow(), {"timer": "window"}, 6_000, 6_010),
    ]
    for action, *_ in window:
        state, _ = apply(state, action)
    steps += window
    assert state.phase is Phase.ASSIGN
    assign = legal_actions(state, presser)[0]
    steps.append((assign, {"seat": presser}, 9_000, 9_020))
    state, _ = apply(state, assign)
    record = corpus_record(
        0,
        [a for a, *_ in steps],
        state,
        game=GAME | {"completion": "abandoned"},
        seats=PEOPLE,
        times=[(r, s) for *_, r, s in steps],
        causes=[c for _, c, *_ in steps],
    )
    assert response_times(read_corpus_record(record)) == (2_000, None, 5_000 - 2_100, None, 2_990)


# ---------------------------------------------------------------- analysis sets (§6)


def flags_for(**changes: Any) -> Any:
    played = website_play(3, 4)
    return analysis_flags(read_corpus_record(record_of(played, **changes)))


def test_a_finished_solo_all_human_game_is_primary() -> None:
    flags = flags_for()
    assert (flags.completed, flags.finished, flags.solo, flags.primary) == (True, True, True, True)
    assert not (flags.bot_seat)
    assert not (flags.note_yes)
    assert not (flags.note_missing)
    assert not (flags.mixed_cohort)


@pytest.mark.parametrize(
    ("changes", "flag"),
    [
        ({"matchmaking": "group"}, "solo"),
        ({"seats": [*PEOPLE[:5], person(5, note="yes")]}, "note_yes"),
        ({"seats": [*PEOPLE[:5], bot("none", None)]}, "bot_seat"),
    ],
    ids=["group", "note", "bot"],
)
def test_what_takes_a_game_out_of_the_primary_set(changes: dict[str, Any], flag: str) -> None:
    flags = flags_for(**changes)
    assert not flags.primary
    assert getattr(flags, flag) is (flag != "solo")


def test_a_handover_counts_as_a_bot_seat() -> None:
    log = [_row("handover", 10, seat=2, reason="disconnect", agent="b1-v1", memory="last-k", k=8)]
    assert flags_for(log=log).bot_seat


def test_missing_note_answers_and_cohorts() -> None:
    seats = [person(0, cohort=True, note="declined"), *PEOPLE[1:5], person(5, note="unanswered")]
    flags = flags_for(seats=seats)
    assert flags.note_missing
    assert flags.mixed_cohort
    assert not flags.all_cohort
    cohort = [person(n, cohort=True) for n in SEATS]
    flags = flags_for(seats=cohort, cohort_table=True)
    assert flags.all_cohort
    assert not flags.mixed_cohort


def test_abandoned_and_unfinished_games() -> None:
    played = website_play(3, 4, max_actions=40)
    game = read_corpus_record(record_of(played))
    assert game.game.completion == "abandoned"
    assert not analysis_flags(game).completed
    unfinished = replace(game, game=replace(game.game, completion="unfinished"))
    flags = analysis_flags(unfinished)
    assert flags.completed
    assert not flags.finished
    assert not flags.primary


# ---------------------------------------------------------------- malformed records


def _row(kind: str, after: int, at_us: int | None = None, **fields: object) -> dict[str, object]:
    return {"type": kind, "after": after, "at_us": after * 1_000 if at_us is None else at_us,
            **fields}  # fmt: skip


BASE_PLAYED = website_play(5, 6)
BASE_LOG = [
    _row("connection", 0, seat=0, state="connected"),
    _row("rtt", 0, seat=0, rtt_us=40_000),
    _row("rejected", 3, seat=1, input={"type": "Shout"}, reason="malformed"),
    _row("handover", 6, seat=5, reason="turn_timeout", agent="b1-v1", memory="last-k", k=8),
    _row("bot_delay", 6, seat=5, delay_us=2_000_000, dropped=False),
    _row("connection", 7, seat=5, state="reconnected"),
]


def base() -> dict[str, Any]:
    return json.loads(json.dumps(record_of(BASE_PLAYED, log=BASE_LOG)))


def test_the_base_record_reads() -> None:
    game = read_corpus_record(base())
    assert isinstance(game, CorpusGame)
    assert game.handover_after(5) == 6
    assert game.handover_after(0) is None
    assert game.person_acts(5, 5)
    assert not game.person_acts(5, 6)
    assert base()["corpus"] == CORPUS_ENCODING


def first(record: dict[str, Any], kind: type) -> int:
    return next(i for i, a in enumerate(record["actions"]) if a["type"] == kind.__name__)


def _set(path: str, value: object) -> Callable[[dict[str, Any]], None]:
    def change(record: dict[str, Any]) -> None:
        *parents, last = path.split(".")
        node: Any = record
        for key in parents:
            node = node[int(key)] if key.isdigit() else node[key]
        node[int(last) if last.isdigit() else last] = value

    return change


def _call(f: Callable[[dict[str, Any]], object]) -> Callable[[dict[str, Any]], None]:
    def change(record: dict[str, Any]) -> None:
        f(record)

    return change


def _open_window_cause(record: dict[str, Any], cause: object) -> None:
    record["causes"][first(record, OpenWindow)] = cause


def _press_received(record: dict[str, Any]) -> None:
    n = first(record, OpenWindow)
    record["times"][n][0] -= 1


def _press_other_seat(record: dict[str, Any]) -> None:
    n = first(record, OpenWindow)
    record["causes"][n] = {"seat": (record["causes"][n]["seat"] + 1) % 6}


def _end_with_open_window(record: dict[str, Any]) -> None:
    n = first(record, OpenWindow)
    for key in ("actions", "times", "causes"):
        record[key] = record[key][: n + 1]
    record["outcome"] = record["winner"] = None
    record["game"]["completion"] = "abandoned"
    record["log"] = []


def _other_seat_asks(record: dict[str, Any]) -> None:
    n = first(record, Ask)
    record["causes"][n] = {"seat": (record["causes"][n]["seat"] + 1) % 6}


def _pass_in_window(record: dict[str, Any]) -> None:
    n = first(record, OpenWindow)
    state = new_game(int(record["seed"]))
    for item in record["actions"][: n + 2]:
        state, _ = apply(state, action_from_data(item))
    other = next(s for s in acting_seats(state))
    at = record["times"][n + 1][1]
    for key in ("actions", "times", "causes"):
        record[key] = record[key][: n + 2]
    record["actions"].append({"type": "Pass", "seat": other})
    record["times"].append([at, at])
    record["causes"].append({"seat": other})
    record["outcome"] = record["winner"] = None
    record["game"]["completion"] = "abandoned"
    record["log"] = []


BAD: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("corpus", _set("corpus", "fish-corpus-v0"), "corpus is"),
    ("game", _set("game", []), "game is an object"),
    ("game keys", _call(lambda r: r["game"].pop("month")), "game has keys"),
    ("month", _set("game.month", "2026-13"), "YYYY-MM"),
    ("completion", _set("game.completion", "abandoned"), "the replay is"),
    ("completion name", _set("game.completion", "done"), "game completion is one of"),
    ("matchmaking", _set("game.matchmaking", "friends"), "matchmaking"),
    ("cohort table type", _set("game.cohort_table", 1), "true or false"),
    ("id", _set("game.id", ""), "1 to 64"),
    ("commit", _set("game.server_commit", "x" * 65), "1 to 64"),
    ("protocol", _set("game.protocol_version", 0), "at least 1"),
    ("seats", _set("seats", {}), "seats is a list"),
    ("five seats", _call(lambda r: r["seats"].pop()), "6 entries"),
    ("seat keys", _call(lambda r: r["seats"][0].pop("k")), "seat 0 has keys"),
    ("person agent", _set("seats.0.agent", "b1-v1"), "seat 0 is a person"),
    ("person memory", _set("seats.0.memory", "full"), "seat 0 is a person"),
    ("person cohort", _set("seats.0.cohort", None), "true or false"),
    ("person note", _set("seats.0.note", "maybe"), "note is one of"),
    ("bot cohort", _set("seats.5", bot() | {"cohort": False}), "seat 5 is a bot"),
    ("bot memory", _set("seats.5", bot("human", None)), "memory is one of"),
    ("bot k", _set("seats.5", bot("last-k", None)), "k is an integer"),
    ("bot k zero", _set("seats.5", bot("last-k", 0)), "k is an integer"),
    ("bot extra k", _set("seats.5", bot("full", 8)), "k only with memory last-k"),
    ("bot agent", _set("seats.5", bot() | {"agent": ""}), "1 to 64"),
    ("no people", _set("seats", [bot() for _ in SEATS]), "at least one person"),
    ("same person", _set("seats.1.person", "p0"), "at most one seat"),
    ("cohort table", _set("game.cohort_table", True), "only cohort players"),
    ("times", _set("times", None), "times is a list"),
    ("times length", _call(lambda r: r["times"].pop()), "one entry per action"),
    ("causes length", _call(lambda r: r["causes"].pop()), "one entry per action"),
    ("time pair", _set("times.0", [1]), "received_us, sent_us"),
    ("time pair list", _set("times.0", 1), "times\\[0\\] is a list"),
    ("negative", _set("times.0", [-1, 0]), "at least 0"),
    ("bool time", _set("times.0", [True, 1]), "at least 0"),
    ("sent first", _set("times.0", [10, 5]), "never going back"),
    ("received back", _set("times.1", [0, 0]), "never going back"),
    ("cause shape", _set("causes.0", {"x": 1}), "causes\\[0\\] has keys"),
    ("cause timer", _set("causes.0", {"timer": "turn"}), "timer is one of"),
    ("cause seat", _set("causes.0", {"seat": 6}), "seat 0-5"),
    ("cause bool", _set("causes.0", {"seat": True}), "seat 0-5"),
    ("own seat", _other_seat_asks, "its own seat"),
    (
        "by timer",
        _call(lambda r: r["causes"].__setitem__(first(r, Ask), {"timer": "window"})),
        "its own seat",
    ),
    (
        "close by seat",
        _call(lambda r: r["causes"].__setitem__(first(r, CloseWindow), {"seat": 0})),
        "window timer",
    ),
    (
        "open by timer",
        _call(lambda r: _open_window_cause(r, {"timer": "window"})),
        "opens with a press",
    ),
    ("press time", _press_received, "opens with a press"),
    ("press seat", _press_other_seat, "opens with a press"),
    ("press last", _end_with_open_window, "opens with a press"),
    ("pass", _pass_in_window, "nobody passes"),
    ("log", _set("log", {}), "log is a list"),
    ("log row", _set("log.0", 1), "type is one of"),
    ("log type", _set("log.0.type", "chat"), "type is one of"),
    ("log keys", _call(lambda r: r["log"][1].pop("rtt_us")), "log\\[1\\] has keys"),
    ("after", _set("log.0.after", 10**6), "never go back"),
    ("after back", _set("log.3.after", 2), "never go back"),
    ("at back", _set("log.3.at_us", 0), "never go back"),
    ("log seat", _set("log.0.seat", 7), "seat 0-5"),
    ("rtt", _set("log.1.rtt_us", -5), "at least 0"),
    ("reason", _set("log.2.reason", "rude"), "reason is one of"),
    ("delay", _set("log.4.delay_us", "2s"), "at least 0"),
    ("dropped", _set("log.4.dropped", None), "true or false"),
    ("state", _set("log.0.state", "away"), "state is one of"),
    ("handover reason", _set("log.3.reason", "bored"), "reason is one of"),
    ("handover agent", _set("log.3.agent", ""), "1 to 64"),
    ("handover memory", _set("log.3.memory", "human"), "memory is one of"),
    ("rtt after handover", _set("log.5", _row("rtt", 7, seat=5, rtt_us=1)), "rtt rows"),
    ("delay for a person", _set("log.4.seat", 4), "bot_delay rows"),
    (
        "handover twice",
        _call(lambda r: r["log"].insert(5, dict(r["log"][3]))),
        "only a person's seat",
    ),
    ("handover a bot", _set("seats.5", bot()), "only a person's seat"),
    (
        "connection for a bot",
        _call(
            lambda r: (
                r["seats"].__setitem__(4, bot()),
                r["log"].append(_row("connection", 8, seat=4, state="connected")),
            )
        ),
        "connection rows",
    ),
]


@pytest.mark.parametrize(("change", "match"), [b[1:] for b in BAD], ids=[b[0] for b in BAD])
def test_bad_records_are_rejected(change: Callable[[dict[str, Any]], None], match: str) -> None:
    record = base()
    change(record)
    with pytest.raises(CorpusError, match=match):
        read_corpus_record(record)


def test_the_writer_refuses_a_bad_record() -> None:
    _, state, actions, causes, times = BASE_PLAYED
    with pytest.raises(CorpusError, match="one entry per action"):
        corpus_record(5, actions, state, game=GAME, seats=PEOPLE, times=times[:-1], causes=causes)
