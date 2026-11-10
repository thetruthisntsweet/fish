"""Tests for fish_server.corpus_export: membership and the export (docs/corpus.md §6, §7).

Real website games (``fish_rules.playout.random_website_game``) are written to the tables
the way the server will write them, then exported. Every exported record must read and
replay to the same game; membership must follow the seats' consent flags and withdrawals;
and nothing internal may leave. Skipped without FISH_TEST_DATABASE_URL.
"""

import gzip
import importlib.util
import json
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Connection, Engine, create_engine, insert, pool, select

from fish_rules.codec import action_to_data
from fish_rules.corpus import analysis_flags, read_corpus_record
from fish_rules.engine import replay
from fish_rules.playout import random_website_game
from fish_rules.state import State, new_game, state_hash
from fish_rules.version import RULESET_VERSION
from fish_server import db
from fish_server.corpus_export import (
    ExportError,
    Summary,
    export,
    main,
    membership,
    records,
    sha256,
)
from fish_server.games import latest_consent
from fish_server.settings import database_url

START = datetime(2026, 12, 1, 20, 0, tzinfo=UTC)


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    """The server's own login: it writes the games and runs the export."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def add_person(conn: Connection, *, cohort: bool = False, consented: bool = True) -> uuid.UUID:
    """A player, with an acceptance of the consent screen unless ``consented`` is False."""
    person = uuid.uuid4()
    number = conn.execute(select(db.signup_numbers.next_value())).scalar_one()
    conn.execute(insert(db.players).values(player_id=person, signup_number=number, cohort=cohort))
    conn.execute(insert(db.player_contacts).values(player_id=person, email=f"{person}@x.org"))
    if consented:
        consent(conn, person)
    return person


def consent(conn: Connection, person: uuid.UUID, version: str = "v1.0") -> None:
    conn.execute(
        insert(db.consents).values(
            player_id=person,
            version=version,
            us_resident_adult=True,
            agrees=True,
            no_outside_communication=True,
        )
    )


def withdraw(conn: Connection, person: uuid.UUID, channel: str = "website") -> None:
    conn.execute(insert(db.withdrawals).values(player_id=person, channel=channel))


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
    bot_delays: str = "uniform-1.5-4s-v1",
    matchmaking: str = "solo",
    cohort_table: bool = False,
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
            bot_delays=bot_delays,
            matchmaking=matchmaking,
            cohort_table=cohort_table,
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
        accepted = None if person is None else latest_consent(conn, person)
        if accepted is not None:  # copied at the start, as fish_server.games does
            conn.execute(
                insert(db.seat_consents).values(
                    game_id=game_id, seat=seat, player_id=person, **accepted
                )
            )
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
    """§7: each corpus game is a fish-corpus-v2 record that reads and replays to the game that
    was played, in order of start time, with release ids and per-export pseudonyms."""
    with app.begin() as conn:
        regulars = table(conn)
        played = [
            add_game(conn, 30, regulars, minutes=20, bot_delays="stand-in-v1")[1],
            add_game(conn, 10, regulars, minutes=0)[1],
            add_game(conn, 20, [*regulars[:3], *people(conn, 3)], minutes=10)[1],
        ]
    with app.connect() as conn:
        records, summary = export(conn)
    assert (summary.games, summary.exported) == (3, 3)
    assert [r["game"]["id"] for r in records] == ["g-000001", "g-000002", "g-000003"]  # type: ignore[index]
    by_seed = {s.seed: s for s in played}
    for record in records:
        game = read_corpus_record(json.loads(json.dumps(record)))
        assert state_hash(game.final) == state_hash(by_seed[game.seed])
        assert game.game.month == "2026-12"
    assert [read_corpus_record(r).seed for r in records] == [10, 20, 30]
    assert [read_corpus_record(r).game.bot_delays for r in records] == [
        "uniform-1.5-4s-v1",
        "uniform-1.5-4s-v1",
        "stand-in-v1",
    ]  # each game's own bots' waits (R.8.8)
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
        records, _ = export(conn)
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
        first, _ = export(conn)
        second, _ = export(conn)
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
        (record,), _ = export(conn)
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


def test_a_withdrawal_removes_every_game_of_that_person_for_good(app: Engine) -> None:
    """Research Plan §6, Consent Screen §3: a withdrawal is a record of its own; every game the
    person played leaves the corpus whole, and accepting again does not bring them back."""
    with app.begin() as conn:
        seated = table(conn)
        add_game(conn, 5, seated)
        add_game(conn, 6, [seated[2], *people(conn, 5)], minutes=1)
        add_game(conn, 7, table(conn), minutes=2)
    with app.connect() as conn:
        assert export(conn)[1].exported == 3
    with app.begin() as conn:
        withdraw(conn, seated[2], "email")  # pyright: ignore[reportArgumentType]
    with app.connect() as conn:
        records, summary = export(conn)
    assert (summary.exported, summary.withdrawn) == (1, 2)
    assert read_corpus_record(records[0]).seed == 7
    with app.begin() as conn:
        consent(conn, seated[2])  # pyright: ignore[reportArgumentType]
    with app.connect() as conn:
        assert export(conn)[1].withdrawn == 2


def test_a_seat_without_consent_flags_removes_the_whole_game(app: Engine) -> None:
    """Research Plan §6: membership comes from the seats' flags, copied when the game started,
    so consenting afterwards does not bring the game in."""
    with app.begin() as conn:
        late = add_person(conn, consented=False)
        add_game(conn, 5, [*people(conn, 5), late])
        add_game(conn, 6, table(conn), minutes=1)
        consent(conn, late)
    with app.connect() as conn:
        records, summary = export(conn)
    assert (summary.exported, summary.unconsented) == (1, 1)
    assert read_corpus_record(records[0]).seed == 6
    assert summary.lines()[5] == "left out, a person's seat without consent: 1"


def test_seats_copy_the_latest_acceptance(app: Engine) -> None:
    with app.begin() as conn:
        person = add_person(conn)
        consent(conn, person, "v1.1")
        game_id, _ = add_game(conn, 5, [person, *people(conn, 5)])
        flags = (
            conn.execute(select(db.seat_consents).where(db.seat_consents.c.game_id == game_id))
            .mappings()
            .all()
        )
    assert len(flags) == 6
    assert [f["version"] for f in flags if f["player_id"] == person] == ["v1.1"]


def test_only_completed_games_with_a_person_enter(app: Engine) -> None:
    """§3, §6: no ending yet, abandoned, and bot-only games stay out."""
    with app.begin() as conn:
        add_game(conn, 1, table(conn), ending=None)
        add_game(conn, 2, table(conn), max_actions=30, minutes=1)
        add_game(conn, 3, [None] * 6, minutes=2)
        add_game(conn, 4, table(conn), minutes=3)
    with app.connect() as conn:
        records, summary = export(conn)
    assert (summary.games, summary.not_ended, summary.abandoned, summary.no_person) == (4, 1, 1, 1)
    assert [read_corpus_record(r).seed for r in records] == [4]
    assert summary.lines()[1] == "exported: 1"


# ---------------------------------------------------------------- refusing bad games


def test_a_game_under_another_ruleset_is_left_out(app: Engine) -> None:
    """R.10.2: games under different ruleset versions are analysed separately, so this
    corpus, of this version's games, leaves an older one out and says so."""
    with app.begin() as conn:
        add_game(conn, 5, table(conn), ruleset="1.1")
        add_game(conn, 6, table(conn))
    with app.connect() as conn:
        records, summary = export(conn)
        assert set(membership(conn).values()) == {"other_ruleset", "exported"}
    assert [read_corpus_record(r).seed for r in records] == [6]
    assert summary.other_ruleset == 1
    assert "left out, played under another ruleset: 1" in summary.lines()


def test_a_record_that_does_not_read_stops_the_export(app: Engine) -> None:
    """A game stopped part-way but recorded as finished: the record would contradict the
    replay, so the export fails rather than write it."""
    with app.begin() as conn:
        add_game(conn, 5, table(conn), max_actions=10, ending="finished")
    with pytest.raises(ExportError, match="is not a valid record"), app.connect() as conn:
        export(conn)


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
        export(conn)


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
        add_game(conn, 5, table(conn), max_actions=10, ending="finished")  # does not read
    out = tmp_path / "corpus.jsonl"
    out.unlink()
    assert main(["--out", str(out)]) == 1
    assert "FAIL game" in capsys.readouterr().err
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []  # no partial file left behind


@pytest.mark.usefixtures("server_env")
def test_records_are_built_one_at_a_time(app: Engine) -> None:
    """The export never holds the whole corpus: it runs on the server's own instance."""
    with app.begin() as conn:
        for n in range(3):
            add_game(conn, 5 + n, table(conn), minutes=n)
    summary = Summary()
    with app.connect() as conn:
        games = records(conn, summary)
        first = next(games)
        assert (first["game"]["id"], summary.exported) == ("g-000001", 1)  # pyright: ignore[reportIndexIssue]
        assert [r["game"]["id"] for r in games] == ["g-000002", "g-000003"]  # pyright: ignore[reportIndexIssue]
    assert (summary.games, summary.exported) == (3, 3)


# ---------------------------------------------------------------- a copy (T3.6)


def _check_export() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "check_export.py"
    spec = importlib.util.spec_from_file_location("check_export", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.usefixtures("server_env")
def test_a_gzipped_export_and_its_copy_check_the_same(
    app: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        add_game(conn, 5, table(conn))
        add_game(conn, 6, table(conn, persons=3), minutes=1)
    out = tmp_path / "corpus-2026-12-14.jsonl.gz"
    assert main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    with gzip.open(out, "rt", encoding="utf-8") as file:
        assert [read_corpus_record(json.loads(line)).seed for line in file] == [5, 6]
    assert f"sha256: {sha256(out)}" in printed
    assert f"file: {out} ({out.stat().st_size:,} bytes)" in printed

    copy = tmp_path / "laptop" / out.name
    copy.parent.mkdir()
    copy.write_bytes(out.read_bytes())
    check = _check_export()
    assert check.main([str(copy)]) == 0
    checked = capsys.readouterr().out.splitlines()
    for line in ("exported: 2", "people: 9", f"sha256: {sha256(out)}"):
        assert line in printed
        assert line in checked
    assert checked[-1].startswith("PASS")


@pytest.mark.usefixtures("server_env")
def test_a_copy_that_is_cut_short_or_altered_fails(
    app: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        add_game(conn, 5, table(conn))
        add_game(conn, 6, table(conn), minutes=1)
    out = tmp_path / "corpus.jsonl.gz"
    assert main(["--out", str(out)]) == 0
    capsys.readouterr()
    check = _check_export()
    cut = tmp_path / "cut.jsonl.gz"
    cut.write_bytes(out.read_bytes()[: out.stat().st_size // 2])
    assert check.main([str(cut)]) == 1
    assert capsys.readouterr().out.startswith(f"FAIL {cut}")

    with gzip.open(out, "rt", encoding="utf-8") as file:
        lines = file.readlines()
    altered = tmp_path / "altered.jsonl"
    record = json.loads(lines[1])
    record["actions"] = record["actions"][:-1]
    altered.write_text(lines[0] + json.dumps(record) + "\n", encoding="utf-8")
    assert check.main([str(altered)]) == 1
    assert capsys.readouterr().out.startswith(f"FAIL {altered}: line 2:")

    reordered = tmp_path / "reordered.jsonl"
    reordered.write_text(lines[1], encoding="utf-8")
    assert check.main([str(reordered)]) == 1
    assert "game g-000002, not g-000001" in capsys.readouterr().out
