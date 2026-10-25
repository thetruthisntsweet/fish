"""Tests for fish_server.corpus_export: membership and the export (docs/corpus.md §6, §7).

Real website games (``fish_rules.playout.random_website_game``) are written to the tables
the way the server will write them, then exported. Every exported record must read and
replay to the same game; membership must follow the latest consent and age events; and
nothing internal may leave. Skipped without FISH_TEST_DATABASE_URL.
"""

import json
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, insert, pool, select

from fish_rules.codec import action_to_data
from fish_rules.corpus import analysis_flags, read_corpus_record
from fish_rules.engine import replay
from fish_rules.playout import random_website_game
from fish_rules.state import State, new_game, state_hash
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.corpus_export import ExportError, eligible_people, export, main
from fish_server.settings import database_url

START = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    """The server's own login: it writes the games and runs the export."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def add_person(
    conn: Connection,
    *,
    cohort: bool = False,
    research: bool | None = True,
    public: bool = True,
    adult: bool | None = True,
) -> uuid.UUID:
    """A player with a consent event and an age event (``None`` leaves one out)."""
    person = uuid.uuid4()
    number = conn.execute(select(db.signup_numbers.next_value())).scalar_one()
    conn.execute(insert(db.players).values(player_id=person, signup_number=number, cohort=cohort))
    conn.execute(insert(db.player_contacts).values(player_id=person, email=f"{person}@x.org"))
    if research is not None:
        consent(conn, person, research=research, public=public)
    if adult is not None:
        conn.execute(insert(db.age_events).values(player_id=person, confirmed_18_plus=adult))
    return person


def consent(conn: Connection, person: uuid.UUID, *, research: bool, public: bool = True) -> None:
    conn.execute(
        insert(db.consent_events).values(
            player_id=person,
            consent_version="v1",
            research_use=research,
            public_release=public,
            no_outside_communication=True,
            no_notes=True,
        )
    )


def add_game(
    conn: Connection,
    seed: int,
    seats: Sequence[uuid.UUID | None],
    *,
    minutes: int = 0,
    max_actions: int = 2_000,
    ending: str | None = "rules",
    log: Sequence[dict[str, object]] = (),
    notes: dict[int, str] | None = None,
    ruleset: str = RULESET_VERSION,
) -> tuple[uuid.UUID, State]:
    """Write one website game. ``seats[s]`` is a person or None for a B1 bot. ``ending`` is
    the completion to record, "rules" for whatever the game reached, or None for no ending."""
    actions, causes, times = random_website_game(seed, seed + 1, max_actions)
    state = new_game(seed)
    for step in replay(seed, actions):
        state = step[0]
    game_id = uuid.uuid4()
    conn.execute(
        insert(db.games).values(
            game_id=game_id,
            seed=seed,
            ruleset=ruleset,
            action_encoding="fish-actions-v1",
            state_encoding="fish-state-v1",
            server_commit="abc1234",
            protocol_version=1,
            matchmaking="solo",
            cohort_table=False,
            started_at=START + timedelta(minutes=minutes),
        )
    )
    for seat, person in enumerate(seats):
        controller = (
            {"player_id": person, "memory": "human"}
            if person is not None
            else {"agent": "b1-v1", "memory": "last-k", "k": 8}
        )
        conn.execute(insert(db.seats).values(game_id=game_id, seat=seat, **controller))
    for seq, (action, cause, (received, sent)) in enumerate(
        zip(actions, causes, times, strict=True)
    ):
        conn.execute(
            insert(db.actions).values(
                game_id=game_id,
                seq=seq,
                action=action_to_data(action),
                cause_seat=cause.get("seat"),
                cause_timer=cause.get("timer"),
                received_us=received,
                sent_us=sent,
            )
        )
    for row in log:
        fields = {k: v for k, v in row.items() if k not in ("type", "after", "at_us", "seat")}
        conn.execute(
            insert(db.server_log).values(
                game_id=game_id,
                after_seq=row["after"],
                at_us=row["at_us"],
                seat=row["seat"],
                type=row["type"],
                data=fields,
            )
        )
    for seat, answer in (notes or {}).items():
        conn.execute(
            insert(db.note_answers).values(
                game_id=game_id, seat=seat, question_version="v1", answer=answer
            )
        )
    if ending is not None:
        completion = ending
        if ending == "rules":
            completion = "abandoned" if state.outcome is None else str(state.outcome)
        conn.execute(insert(db.game_endings).values(game_id=game_id, completion=completion))
    return game_id, state


def people(conn: Connection, count: int) -> list[uuid.UUID | None]:
    """``count`` new eligible people."""
    return [add_person(conn) for _ in range(count)]


def table(conn: Connection, persons: int = 6) -> list[uuid.UUID | None]:
    """Six seats: ``persons`` new eligible people, then B1 bots."""
    return people(conn, persons) + [None] * (6 - persons)


# ---------------------------------------------------------------- the export


def test_every_corpus_game_becomes_a_record_that_replays(app: Engine) -> None:
    """§7: each corpus game is a fish-corpus-v1 record that reads and replays to the game that
    was played, in order of start time, with release ids and per-export pseudonyms."""
    with app.begin() as conn:
        regulars = table(conn)
        played = [
            add_game(conn, 30, regulars, minutes=20)[1],
            add_game(conn, 10, regulars, minutes=0)[1],
            add_game(conn, 20, [*regulars[:3], *people(conn, 3)], minutes=10)[1],
        ]
    with app.connect() as conn:
        records, summary = export(conn, public=False)
    assert (summary.games, summary.exported) == (3, 3)
    assert [r["game"]["id"] for r in records] == ["g-000001", "g-000002", "g-000003"]  # type: ignore[index]
    by_seed = {s.seed: s for s in played}
    for record in records:
        game = read_corpus_record(json.loads(json.dumps(record)))
        assert state_hash(game.final) == state_hash(by_seed[game.seed])
        assert game.game.month == "2026-12"
    assert [read_corpus_record(r).seed for r in records] == [10, 20, 30]
    first, second, _ = (read_corpus_record(r).seats for r in records)
    assert [s.person for s in first[:3]] == [s.person for s in second[:3]]
    assert [s.person for s in first[3:]] != [s.person for s in second[3:]]
    assert len(summary.pseudonyms) == 9


def test_nothing_internal_leaves(app: Engine) -> None:
    """§7: no internal player or game id, email address or wall-clock time in the export."""
    with app.begin() as conn:
        seated = table(conn)
        game_id, _ = add_game(conn, 5, seated)
    with app.connect() as conn:
        records, _ = export(conn, public=True)
    text = json.dumps(records)
    assert str(game_id) not in text
    assert not any(str(person) in text for person in seated)
    assert "@" not in text
    assert "2026-12-01" not in text
    assert "20:00" not in text


def test_two_exports_use_different_pseudonyms(app: Engine) -> None:
    with app.begin() as conn:
        add_game(conn, 5, table(conn))
    with app.connect() as conn:
        first, _ = export(conn, public=False)
        second, _ = export(conn, public=False)
    assert first[0]["seats"] != second[0]["seats"]
    assert {k: v for k, v in first[0].items() if k != "seats"} == {
        k: v for k, v in second[0].items() if k != "seats"
    }


def test_bots_notes_and_log_rows_carry_over(app: Engine) -> None:
    """§4, §5.2: bot seats, note answers (none is unanswered) and server log rows."""
    log = [
        {"type": "connection", "after": 0, "at_us": 0, "seat": 0, "state": "connected"},
        {"type": "rtt", "after": 0, "at_us": 10, "seat": 0, "rtt_us": 40_000},
        {"type": "handover", "after": 3, "at_us": 20, "seat": 4, "reason": "disconnect",
         "agent": "b1-v1", "memory": "last-k", "k": 8},
        {"type": "bot_delay", "after": 3, "at_us": 30, "seat": 5, "delay_us": 2_000_000,
         "dropped": True},
    ]  # fmt: skip
    with app.begin() as conn:
        add_game(conn, 5, table(conn, 5), log=log, notes={0: "yes", 1: "declined"})
    with app.connect() as conn:
        (record,), _ = export(conn, public=False)
    game = read_corpus_record(record)
    assert [s.note for s in game.seats] == ["yes", "declined", "unanswered", "unanswered",
                                            "unanswered", None]  # fmt: skip
    assert (game.seats[5].agent, game.seats[5].memory, game.seats[5].k) == ("b1-v1", "last-k", 8)
    assert [row.type for row in game.log] == ["connection", "rtt", "handover", "bot_delay"]
    assert game.handover_after(4) == 3
    flags = analysis_flags(game)
    assert flags.bot_seat
    assert flags.note_yes
    assert not flags.primary


# ---------------------------------------------------------------- membership (§6)


def test_a_withdrawal_removes_the_game_and_consent_again_returns_it(app: Engine) -> None:
    """§6: membership follows the latest consent event, at every export."""
    with app.begin() as conn:
        seated = table(conn)
        add_game(conn, 5, seated)
    with app.connect() as conn:
        assert export(conn, public=False)[1].exported == 1
    with app.begin() as conn:
        consent(conn, seated[2], research=False)  # pyright: ignore[reportArgumentType]
    with app.connect() as conn:
        records, summary = export(conn, public=False)
    assert (records, summary.ineligible) == ([], 1)
    with app.begin() as conn:
        consent(conn, seated[2], research=True)  # pyright: ignore[reportArgumentType]
    with app.connect() as conn:
        assert export(conn, public=False)[1].exported == 1


@pytest.mark.parametrize(
    "person",
    [{"research": None}, {"research": False}, {"adult": None}, {"adult": False}],
    ids=["no consent", "consent refused", "no age check", "under 18"],
)
def test_one_ineligible_person_removes_the_whole_game(
    app: Engine, person: dict[str, bool | None]
) -> None:
    with app.begin() as conn:
        seats = [*people(conn, 5), add_person(conn, **person)]  # pyright: ignore[reportArgumentType]
        add_game(conn, 5, seats)
        add_game(conn, 6, table(conn), minutes=1)
    with app.connect() as conn:
        records, summary = export(conn, public=False)
    assert (summary.exported, summary.ineligible) == (1, 1)
    assert read_corpus_record(records[0]).seed == 6


def test_the_public_release_also_needs_release_consent(app: Engine) -> None:
    with app.begin() as conn:
        add_game(conn, 5, [*people(conn, 5), add_person(conn, public=False)])
        eligible_research = eligible_people(conn, public=False)
        eligible_public = eligible_people(conn, public=True)
    assert len(eligible_research) == 6
    assert len(eligible_public) == 5
    with app.connect() as conn:
        assert export(conn, public=False)[1].exported == 1
        assert export(conn, public=True)[1].ineligible == 1


def test_only_completed_games_with_a_person_enter(app: Engine) -> None:
    """§3, §6: no ending yet, abandoned, and bot-only games stay out."""
    with app.begin() as conn:
        add_game(conn, 1, table(conn), ending=None)
        add_game(conn, 2, table(conn), max_actions=30, minutes=1)
        add_game(conn, 3, [None] * 6, minutes=2)
        add_game(conn, 4, table(conn), minutes=3)
    with app.connect() as conn:
        records, summary = export(conn, public=False)
    assert (summary.games, summary.not_ended, summary.abandoned, summary.no_person) == (4, 1, 1, 1)
    assert [read_corpus_record(r).seed for r in records] == [4]
    assert summary.lines()[1] == "exported: 1"


# ---------------------------------------------------------------- refusing bad games


def test_a_game_under_another_ruleset_stops_the_export(app: Engine) -> None:
    with app.begin() as conn:
        add_game(conn, 5, table(conn), ruleset="1.0")
    with pytest.raises(ExportError, match=r"ruleset '1\.0'"), app.connect() as conn:
        export(conn, public=False)


def test_a_record_that_does_not_read_stops_the_export(app: Engine) -> None:
    """A game stopped part-way but recorded as finished: the record would contradict the
    replay, so the export fails rather than write it."""
    with app.begin() as conn:
        add_game(conn, 5, table(conn), max_actions=10, ending="finished")
    with pytest.raises(ExportError, match="is not a valid record"), app.connect() as conn:
        export(conn, public=False)


def test_an_illegal_stored_action_stops_the_export(app: Engine) -> None:
    with app.begin() as conn:
        game_id, _ = add_game(conn, 5, table(conn))
        conn.execute(
            insert(db.actions).values(
                game_id=game_id, seq=10_000, action={"type": "OpenWindow"}, cause_seat=0,
                received_us=10**12, sent_us=10**12,
            )
        )  # fmt: skip
    with pytest.raises(ExportError, match="does not replay"), app.connect() as conn:
        export(conn, public=False)


# ---------------------------------------------------------------- the command


@pytest.mark.usefixtures("server_env")
def test_the_command_writes_json_lines(
    app: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        add_game(conn, 5, table(conn))
        add_game(conn, 6, table(conn), minutes=1)
    out = tmp_path / "corpus.jsonl"
    assert main(["--out", str(out)]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert [read_corpus_record(json.loads(line)).seed for line in lines] == [5, 6]
    assert "exported: 2" in capsys.readouterr().out


@pytest.mark.usefixtures("server_env")
def test_the_command_refuses_to_overwrite_and_reports_failures(
    app: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    existing = tmp_path / "corpus.jsonl"
    existing.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        main(["--out", str(existing)])
    assert stopped.value.code == 2
    with app.begin() as conn:
        add_game(conn, 5, table(conn), ruleset="1.0")
    out = tmp_path / "public.jsonl"
    assert main(["--out", str(out), "--public"]) == 1
    assert "FAIL game" in capsys.readouterr().err
    assert not out.exists()
