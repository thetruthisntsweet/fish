"""How the study is going (fish_server.stats; T4.1, T4.4): corpus games counted exactly as the
export decides, each week's pace against 110 with the rule for adding a night, bot handovers,
game length, and nothing that names anyone. The database tests are skipped without
FISH_TEST_DATABASE_URL."""

import importlib.util
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, pool

from fish_rules.corpus import analysis_flags, read_corpus_record
from fish_server.corpus_export import Standing, export
from fish_server.settings import CONSENT_VERSION_VAR, database_url
from fish_server.stats import DISK_GB, FULL, Game, People, main, read, report


def _games_writer() -> ModuleType:
    """The export tests' writer of real website games, so both count the same games."""
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


written = _games_writer()
PEOPLE = People(signed_up=40, group_1=34, group_2=6, accepted=39, withdrawn=1)


def game(
    day: date,
    standing: Standing = "exported",
    *,
    cohort_table: bool = False,
    bot: bool = False,
    minutes: float | None = None,
    handovers: tuple[str, ...] = (),
    **sets: Any,
) -> Game:
    return Game(uuid.uuid4(), day, standing, cohort_table, bot, minutes, handovers, **sets)


def week_of(
    monday: date, count: int, *, cohort_table: bool = False, bot: bool = False
) -> list[Game]:
    """``count`` corpus games, all on that week's Sunday."""
    sunday = monday + timedelta(days=6)
    return [game(sunday, cohort_table=cohort_table, bot=bot) for _ in range(count)]


def shown(games: list[Game], today: date, current: str = "v1.0", people: People = PEOPLE) -> str:
    return "\n".join(report(people, games, today, current))


# ---------------------------------------------------------------- the report


def test_the_report_counts_people_and_the_corpus_against_its_target() -> None:
    games = [
        *week_of(date(2026, 12, 7), 3),
        game(date(2026, 12, 13), "abandoned"),
        game(date(2026, 12, 13), "withdrawn"),
        game(date(2026, 12, 14), "not_ended"),
        game(date(2026, 12, 13), bot=True),
    ]
    text = shown(games, date(2026, 12, 14))
    assert text.startswith("Fish study on Mon 14 Dec 2026 (Eastern), study information v1.0\n")
    for line in [
        "  signed up                   40  (group 1: 34, group 2: 6)",
        "  accepted v1.0               39",
        "  withdrawn                    1",
        "  in the corpus                4 of 1,000",
        "  playing now                  1",
        "  ended, left out              2  (abandoned 1, a person withdrew 1)",
        "  a bot held a seat            1  (25% of corpus)",
    ]:
        assert f"\n{line}\n" in text
    assert "@" not in text  # counts only, never an address


def test_each_week_shows_its_corpus_games_tables_and_bots() -> None:
    games = [
        *week_of(date(2026, 12, 14), 5, cohort_table=True),
        *week_of(date(2026, 12, 14), 2, bot=True),
        game(date(2026, 12, 20), "abandoned"),
        game(date(2026, 12, 23)),
    ]
    text = shown(games, date(2026, 12, 23))
    assert "  Week (Mon - Sun)        corpus  started  group 2 tables  bot held a seat" in text
    assert "  Mon 14 Dec - Sun 20 Dec      7        8               5                2\n" in text
    assert (
        "  Mon 21 Dec - Sun 27 Dec      1        1               0                0  (so far)"
        in text
    )


def test_a_week_short_of_110_says_so_and_two_say_add_a_night() -> None:
    weeks = [date(2026, 12, 14), date(2026, 12, 21), date(2026, 12, 28)]
    games = week_of(weeks[0], 120) + week_of(weeks[1], 90)
    one = shown(games, date(2026, 12, 29))
    assert "  last full week (Mon 21 Dec): 90  short" in one
    assert "Two full weeks in a row short" not in one
    two = shown(games + week_of(weeks[2], 100), date(2027, 1, 4))
    assert "  last full week (Mon 28 Dec): 100  short" in two
    assert "  at the last two weeks' rate: about 880 by the last day" in two  # 310 + 95 x 6
    assert "  Two full weeks in a row short: add a Friday night (docs/recruitment.md §3)." in two
    enough = shown(week_of(weeks[0], 110), date(2026, 12, 22))
    assert "  last full week (Mon 14 Dec): 110\n" in enough
    assert "  at the last week's rate:" in enough


def test_the_launch_week_and_this_week_are_not_full_weeks() -> None:
    games = [*week_of(date(2026, 12, 7), 50), game(date(2026, 12, 15))]
    assert "  no full week yet" in shown(games, date(2026, 12, 16))


def test_the_pilot_site_gives_game_length_but_no_target() -> None:
    games = [game(date(2026, 12, 1), minutes=m) for m in (18, 22, 25, 30, 41)]
    text = shown(games, date(2026, 12, 6), "v1.0-pilot")
    assert "  in the corpus                5\n" in text
    assert "  minutes a game takes        25  (middle half 20 to 36; 5 finished games)" in text
    assert "of 1,000" not in text
    assert "Pace" not in text
    single = shown([game(date(2026, 12, 1), minutes=24.4)], date(2026, 12, 6), "v1.0-pilot")
    assert "  minutes a game takes        24  (middle half 24 to 24; 1 finished games)" in single


def test_days_with_games_are_listed_for_the_last_two_weeks() -> None:
    games = [
        game(date(2026, 12, 13)),
        game(date(2026, 12, 13), "abandoned"),
        game(date(2026, 11, 1)),
    ]
    text = shown(games, date(2026, 12, 14))
    listed = text[text.index("  Day (last 14 days)      corpus  started") :]
    assert "  Sun 13 Dec                   1        2" in listed
    assert "Sun 1 Nov" not in listed  # more than 14 days ago


def test_nothing_played_yet_reads_cleanly() -> None:
    text = shown([], date(2026, 12, 1), people=People(0, 0, 0, 0, 0))
    assert "  in the corpus                0 of 1,000" in text
    assert "  a bot held a seat            0  (- of corpus)" in text
    assert "Week (" not in text
    assert "minutes a game takes" not in text
    assert "Day (" not in text


# ---------------------------------------------------------------- from the database


@pytest.fixture
def app(server_env: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    monkeypatch.delenv(CONSENT_VERSION_VAR, raising=False)
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def test_handovers_are_counted_by_why() -> None:
    games = [
        game(date(2026, 12, 13), bot=True, handovers=("disconnect", "turn_timeout")),
        game(date(2026, 12, 13), bot=True, handovers=("disconnect",)),
        game(date(2026, 12, 13), "abandoned", bot=True, handovers=("disconnect",)),
    ]
    assert "  seats handed to a bot        4  (a person dropped out 3, a turn ran out 1)" in shown(
        games, date(2026, 12, 14)
    )
    assert "seats handed to a bot" not in shown([game(date(2026, 12, 13))], date(2026, 12, 14))


def test_the_analysis_sets_are_counted_within_the_corpus() -> None:
    sunday, later = date(2026, 12, 13), date(2026, 12, 20)
    games = [
        *[game(sunday) for _ in range(5)],  # primary, group 1
        *[game(sunday, people="group 2", cohort_table=True) for _ in range(2)],
        game(sunday, bot=True, handovers=("disconnect",)),
        game(sunday, solo=False, people="mixed"),  # a room
        game(sunday, note_yes=True),
        game(sunday, finished=False),  # 1,000 asks
        game(sunday, "withdrawn"),  # not in the corpus, so in no set
        game(sunday, "abandoned", bot=True, handovers=("turn_timeout",)),
        game(later, note_missing=True),  # still primary
        game(later, bot=True, handovers=("turn_timeout", "disconnect")),
    ]
    report_ = shown(games, date(2026, 12, 28))
    for line in (
        "Analysis sets (of the corpus)",
        "  primary set                  8  (62% of corpus; group 1: 6, group 2: 2)",
        "  held-out test set            2  (group 2's primary games)",
        "  with a bot handover          2  (15% of corpus)",
        "  joined as a room             1",
        "  a yes to note-taking         1",
        "  a note answer missing        1",
        "  finished                    12  (the rest reached 1,000 asks, R.8.2)",
        "  Week, analysis sets     corpus  primary  group 2 primary  with a handover",
        "  Mon 7 Dec - Sun 13 Dec      11        7                2           1 (9%)",
        "  Mon 14 Dec - Sun 20 Dec      2        1                0          1 (50%)",
    ):
        assert line in report_, line
    assert "Analysis sets" not in shown(games, date(2026, 12, 6), "v1.0-pilot")


def test_the_database_size_is_shown_against_the_disk_and_the_target() -> None:
    games = [game(date(2026, 12, 13)) for _ in range(200)]
    mb = 1024**2
    report_ = "\n".join(report(PEOPLE, games, date(2026, 12, 14), "v1.0", 120 * mb))
    assert "\nDatabase\n  size, MB                   120  (2% of the disk)" in report_
    assert "  at 1,000 corpus games, about 600 MB" in report_
    assert "raise diskSizeGB" not in report_
    full = int(FULL * DISK_GB["study"] * 1024**3)
    assert "past 80%: raise diskSizeGB in render.yaml" in "\n".join(
        report(PEOPLE, games, date(2026, 12, 14), "v1.0", full)
    )
    pilot = "\n".join(report(PEOPLE, games, date(2026, 12, 6), "v1.0-pilot", 512 * mb))
    assert "  size, MB                   512  (50% of the disk)" in pilot  # staging's 1 GB
    assert "corpus games, about" not in pilot
    assert "Database" not in shown(games, date(2026, 12, 14))  # without a size


def test_the_database_is_read_as_the_export_reads_it(app: Engine) -> None:
    late = 12 * 24 * 60 + 7 * 60  # from 1 Dec, 20:00 UTC: 03:00 UTC on 14 Dec, 13 Dec Eastern
    handover = {
        "type": "handover",
        "after": 3,
        "at_us": 1,
        "seat": 2,
        "reason": "turn_timeout",
        "agent": "b1-v1",
        "memory": "last-k",
        "k": 8,
    }
    with app.begin() as conn:
        kept, _ = written.add_game(conn, 11, written.table(conn), minutes=late)
        with_bot, _ = written.add_game(conn, 12, written.table(conn), log=[handover])
        short, _ = written.add_game(conn, 13, written.table(conn, persons=5))
        withdrew = written.table(conn)
        gone, _ = written.add_game(conn, 14, withdrew)
        written.withdraw(conn, withdrew[0])
        playing, _ = written.add_game(conn, 15, written.table(conn), ending=None)
        written.add_person(conn, cohort=True, consented=False)
        ours = [written.add_person(conn, cohort=True) for _ in range(6)]
        held_out, _ = written.add_game(conn, 16, ours, cohort_table=True, notes={0: "no"})
        both = [*written.table(conn, persons=5)[:5], ours[0]]
        room, _ = written.add_game(conn, 17, both, matchmaking="group", notes={2: "yes"})
        answered = dict.fromkeys(range(6), "no")
        whole, _ = written.add_game(conn, 18, written.table(conn), notes=answered)
        noted, _ = written.add_game(conn, 19, written.table(conn), notes=answered | {3: "yes"})
    with app.connect() as conn:
        people, games, _ = read(conn, "v1.0")
        records, summary = export(conn)
    by_id = {g.id: g for g in games}
    assert people == People(signed_up=53, group_1=46, group_2=7, accepted=52, withdrawn=1)
    # The sets, as the records' own flags give them (fish_rules.corpus.analysis_flags).
    flags = [analysis_flags(read_corpus_record(r)) for r in records]
    theirs = Counter(
        (f.primary, f.solo, f.bot_seat, f.note_yes, f.note_missing, f.all_cohort, f.mixed_cohort)
        for f in flags
    )
    mine = Counter(
        (g.primary, g.solo, g.bot, g.note_yes, g.note_missing, g.people == "group 2",
         g.people == "mixed")
        for g in games
        if g.standing == "exported"
    )  # fmt: skip
    assert mine == theirs
    assert (by_id[held_out].people, by_id[room].people) == ("group 2", "mixed")
    assert (by_id[room].solo, by_id[room].note_yes, by_id[room].primary) == (False, True, False)
    assert (by_id[whole].note_missing, by_id[held_out].note_missing) == (False, True)
    assert by_id[held_out].primary
    assert (by_id[noted].note_yes, by_id[noted].primary, by_id[whole].primary) == (
        True,
        False,
        by_id[whole].finished,
    )
    assert sum(g.standing == "exported" for g in games) == summary.exported
    assert (by_id[gone].standing, by_id[playing].standing) == ("withdrawn", "not_ended")
    assert by_id[kept].day == date(2026, 12, 13)
    assert (by_id[with_bot].bot, by_id[short].bot, by_id[kept].bot) == (True, True, False)
    assert by_id[with_bot].handovers == ("turn_timeout",)
    assert by_id[short].handovers == ()  # a bot from the start is no handover
    minutes = [g.minutes for g in games if g.minutes is not None]
    assert minutes
    assert all(0 < m < 120 for m in minutes)


def test_the_command_prints_the_report(app: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    with app.begin() as conn:
        written.add_game(conn, 21, written.table(conn))
    assert main([], create_engine(database_url(), poolclass=pool.NullPool)) == 0
    out = capsys.readouterr().out
    assert "study information v1.0" in out
    assert "\nDatabase\n  size, MB" in out
    assert "  signed up                    6  (group 1: 6, group 2: 0)" in out
