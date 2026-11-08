"""The bots' delay tables (fish_agents.delays; R.8.8, T4.2): every table shipped reads, a table
is built from the pilot report as it says, and ``scripts/make_bot_delays.py`` writes one and
never overwrites one."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from fish_agents import delays
from fish_agents.delays import (
    KIND_OF_PHASE,
    KINDS,
    MIN_TIMES,
    POINTS,
    UNIFORM,
    UNIFORM_MAX_US,
    UNIFORM_MIN_US,
    DelayTable,
    check,
    from_report,
    load,
    versions,
)
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase

SCRIPT = Path(__file__).parents[3] / "scripts" / "make_bot_delays.py"


def report(counts: dict[str, int] | None = None, low: int = 0) -> dict[str, object]:
    """A pilot report's ``--out`` data: each kind's percentiles from ``low`` up by 10 ms."""
    counts = counts or dict.fromkeys(KINDS, 200)
    return {
        "since": "2026-12-01",
        "games": {"exported": 30},
        "response_times_us": {
            kind: {"count": counts[kind], "percentiles": [low + 10_000 * p for p in range(POINTS)]}
            for kind in KINDS
        },
    }


def test_every_table_shipped_reads_and_the_uniform_one_is_built_in() -> None:
    assert versions()[0] == UNIFORM
    assert "stand-in-v1" in versions()
    for version in versions():
        assert load(version).version == version
    assert load(UNIFORM).percentiles is None


def test_every_phase_a_seat_can_act_in_has_a_kind() -> None:
    assert set(KIND_OF_PHASE) == set(Phase) - {Phase.OVER}
    assert set(KIND_OF_PHASE.values()) == set(KINDS)


def test_a_table_is_the_reports_percentiles_with_none_below_zero() -> None:
    data = from_report(report(low=-25_000), "pilot-test-v1", "a test")
    table = check(data)
    assert table.version == "pilot-test-v1"
    assert not table.stand_in
    assert table.percentiles is not None
    assert table.percentiles["turn"][:4] == (0, 0, 0, 5_000)  # -25, -15, -5 ms raised to zero
    assert data["counts"] == dict.fromkeys(KINDS, 200)


def test_a_kind_with_too_few_times_makes_no_table() -> None:
    few = dict.fromkeys(KINDS, 200) | {"assign": MIN_TIMES - 1}
    with pytest.raises(ValueError, match="an assignment: 49 response times, too few"):
        from_report(report(few), "pilot-test-v1", "a test")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["percentiles"].pop("press"), "exactly turn, press, assign, choice"),
        (lambda d: d["percentiles"]["turn"].pop(), "101 whole microseconds"),
        (lambda d: d["percentiles"]["turn"].reverse(), "in order"),
        (lambda d: d["percentiles"]["choice"].__setitem__(0, -1), "none below zero"),
        (lambda d: d["percentiles"]["choice"].__setitem__(0, 1.5), "whole microseconds"),
    ],
)
def test_a_table_that_is_wrong_does_not_read(change: object, message: str) -> None:
    data = from_report(report(), "pilot-test-v1", "a test")
    change(data)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match=message):
        check(data)


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_bot_delays", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_writes_a_new_table_and_never_changes_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    pilot = tmp_path / "pilot.json"
    pilot.write_text(json.dumps(report()))
    tables = tmp_path / "tables"
    tables.mkdir()
    assert script.main([str(pilot), "pilot-test-v1"], tables) == 0
    assert 'BOT_DELAYS = "pilot-test-v1"' in capsys.readouterr().out
    written = json.loads((tables / "pilot-test-v1.json").read_text())
    assert check(written).version == "pilot-test-v1"
    assert written["source"] == (
        "The pilot: 30 corpus games started from 2026-12-01 (fish_server.pilot_report)."
    )
    with pytest.raises(SystemExit):
        script.main([str(pilot), "pilot-test-v1"], tables)
    assert "exists already" in capsys.readouterr().err
    pilot.write_text(json.dumps(report(dict.fromkeys(KINDS, 3))))
    assert script.main([str(pilot), "pilot-test-v2"], tables) == 1
    assert not (tables / "pilot-test-v2.json").exists()


def test_a_table_file_must_name_its_own_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = from_report(report(), "pilot-test-v1", "a test")
    (tmp_path / "pilot-test-v2.json").write_text(json.dumps(data))
    monkeypatch.setattr(delays, "_folder", lambda: tmp_path)
    assert versions() == [UNIFORM, "pilot-test-v2"]
    with pytest.raises(ValueError, match=r"pilot-test-v2\.json says it is 'pilot-test-v1'"):
        load("pilot-test-v2")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"percentiles": {}}, "needs a version"),
        ({"version": ""}, "needs a version"),
        ({"version": "t-v1", "stand_in": "yes"}, "stand_in is true or false"),
    ],
)
def test_a_table_without_a_version_or_with_a_strange_flag_does_not_read(
    data: dict[str, object], message: str
) -> None:
    if "stand_in" in data:
        data = from_report(report(), "t-v1", "a test") | data
    with pytest.raises(ValueError, match=message):
        check(data)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r.pop("response_times_us"), "not a pilot report"),
        (lambda r: r["response_times_us"].pop("press"), "no response times for press"),
        (lambda r: r["response_times_us"]["turn"]["percentiles"].pop(), "should have 101"),
    ],
)
def test_a_report_that_is_not_one_makes_no_table(change: object, message: str) -> None:
    data = report()
    change(data)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match=message):
        from_report(data, "pilot-test-v1", "a test")


def test_a_wait_comes_from_its_kinds_row_linearly_between_percentiles() -> None:
    rows = {kind: tuple(n * 1_000_000 + 10_000 * p for p in range(POINTS))
            for n, kind in enumerate(KINDS, start=1)}  # fmt: skip
    table = DelayTable("t-v1", rows)

    class Fixed(SplitMix64):
        def below(self, n: int) -> int:
            assert n == 100_000_000
            return 2_500_000  # halfway from the 2nd percentile to the 3rd

    assert [table.draw(Fixed(0), kind) for kind in KINDS] == [
        n * 1_000_000 + 25_000 for n in range(1, 5)
    ]
    waits = [load(UNIFORM).draw(SplitMix64(1), kind) for kind in KINDS]
    assert len(set(waits)) == 1  # uniform: the same whatever the kind
    assert UNIFORM_MIN_US <= waits[0] <= UNIFORM_MAX_US
    with pytest.raises(ValueError, match="no kind of decision 'ask'"):
        table.draw(SplitMix64(0), "ask")
    with pytest.raises(ValueError, match="no delay table 'pilot-v9'"):
        load("pilot-v9")


def test_a_dry_run_writes_where_it_is_told(tmp_path: Path) -> None:
    pilot = tmp_path / "pilot.json"
    pilot.write_text(json.dumps(report()))
    elsewhere = tmp_path / "dry" / "run"
    assert _script().main([str(pilot), "rehearsal-v1", "--tables", str(elsewhere)]) == 0
    assert check(json.loads((elsewhere / "rehearsal-v1.json").read_text())).version == (
        "rehearsal-v1"
    )
