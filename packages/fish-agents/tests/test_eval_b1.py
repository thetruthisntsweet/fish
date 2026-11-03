"""B1's evaluation (scripts/eval_b1.py) plays every matchup in parallel, checks every game,
and fails, naming the game, if a call B1 proved was wrong."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fish_rules.events import CallEvent
from fish_rules.state import CallSource

SCRIPTS = Path(__file__).parents[3] / "scripts"
SCRIPT = SCRIPTS / "eval_b1.py"


def load() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))  # it imports the B0 soak's checks
    try:
        spec = importlib.util.spec_from_file_location("eval_b1", SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def test_every_matchup_is_played_and_reported(tmp_path: Path) -> None:
    out = tmp_path / "eval.json"
    args = ["--games", "1", "--workers", "2", "--memories", "full,none", "--json", str(out)]
    run = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert (result["agent"], result["failures"], result["games_played"]) == ("b1-v1", 0, 8)
    rows = {(r["matchup"], r["memory"]): r for r in result["rows"]}
    assert set(rows) == {("b0", "full"), ("b0", "none"), ("full", "none"), ("self", "full"),
                         ("self", "none")}  # fmt: skip
    against_b0 = rows["b0", "full"]
    assert (against_b0["games"], against_b0["finished"], against_b0["won"]) == (2, 2, 2)
    assert against_b0["proved_calls"] > 0
    assert rows["self", "full"]["won"] is None  # a team of B1s against itself
    assert rows["self", "none"]["finished"] == 0  # 1,000 asks without a result (D85)
    assert "| b0 | full | 2 | 2 | 2 (1.0) |" in run.stdout


def test_a_proved_call_that_was_wrong_fails_the_game() -> None:
    evaluation = load()
    right = CallEvent(5, 0, 1, CallSource.WINDOW, (0,) * 6, (0,) * 6, True, 0)
    wrong = CallEvent(9, 3, 2, CallSource.TURN, (3,) * 6, (4,) * 6, False, 0)
    forced = CallEvent(12, 1, 4, CallSource.RUNOUT, (2,) * 6, (1,) * 6, False, 1)
    calls = [right, wrong, forced]
    assert evaluation.tally(calls, {(0, 1)}, [right, forced]) == (1, 0)  # forced, and lost
    with pytest.raises(evaluation.InvariantError, match="seat 3 proved set 2, wrongly"):
        evaluation.tally(calls, {(0, 1), (3, 2)}, [])


def test_a_failure_names_its_game_and_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evaluation = load()

    def broken(seed: int, record: object) -> Any:
        raise evaluation.InvariantError("R.9: more than nine calls")

    monkeypatch.setattr(evaluation, "check_record", broken)
    failed = evaluation.play(evaluation.Game("b0", "full", 1, 7))
    assert failed.failure == "InvariantError: R.9: more than nine calls"
    monkeypatch.setattr(evaluation, "ProcessPoolExecutor", _InProcess)
    out = tmp_path / "eval.json"
    assert evaluation.main(["--games", "1", "--memories", "none", "--json", str(out)]) == 1
    first = json.loads(out.read_text(encoding="utf-8"))["first_failure"]
    assert (first["matchup"], first["memory"], first["seed"]) == ("b0", "none", 0)


def test_the_wilson_interval() -> None:
    evaluation = load()
    assert evaluation.wilson(0, 0) == (0.0, 1.0)
    low, high = evaluation.wilson(5, 10)
    assert (round(low, 3), round(high, 3)) == (0.237, 0.763)
    assert evaluation.wilson(10, 10)[1] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("args", "reason"),
    [(["--games", "0"], "at least 1"), (["--memories", "full,last-5"], "not 'last-5'")],
)
def test_the_evaluation_refuses_what_it_cannot_run(args: list[str], reason: str) -> None:
    run = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert run.returncode == 2
    assert reason in run.stderr


class _InProcess:
    """Stands in for the process pool, so a patched function is the one that runs."""

    def __init__(self, max_workers: int) -> None:
        self.workers = max_workers

    def __enter__(self) -> _InProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def map(
        self, function: Callable[..., object], *iterables: Iterable[object], chunksize: int = 1
    ) -> Iterator[object]:
        return map(function, *iterables, strict=True)
