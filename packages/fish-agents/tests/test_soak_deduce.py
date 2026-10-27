"""The nightly Layer 1 soak (scripts/soak_deduce.py) checks B0 games in parallel and reports
the first seed whose deduction is wrong."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

from fish_rules.deduce.solve import Deduction

SCRIPT = Path(__file__).parents[3] / "scripts" / "soak_deduce.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("soak_deduce", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_soak_checks_games_on_two_workers(tmp_path: Path) -> None:
    out = tmp_path / "soak.json"
    args = ["--games", "4", "--workers", "2", "--chunk", "2", "--probe", "3", "--json", str(out)]
    run = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert (result["games_checked"], result["failures"]) == (4, 0)
    assert result["deductions"] > 0
    assert result["deals_replayed"] > 0
    assert "| games_checked | 4 |" in run.stdout


@pytest.mark.parametrize("wrong", ["holders", "example"])
def test_a_wrong_deduction_names_its_seed(monkeypatch: pytest.MonkeyPatch, wrong: str) -> None:
    soak = load()
    real = soak.deduce

    def broken(*args: object, **kwargs: object) -> Deduction:
        d: Deduction = real(*args, **kwargs)
        if wrong == "holders":
            return soak.replace(d, holders=(0,) * 54)  # every card in play loses its holder
        return soak.replace(d, example=((), (), (), (), (), ()))

    monkeypatch.setattr(soak, "deduce", broken)
    games, *_, failure = soak.check_range(7, 2, 20)
    assert games == 0
    assert failure.startswith("7: DeductionError: after action 0, seat 0: ")


def test_a_deal_that_shows_something_else_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """If Layer 1 named a seat that a deal could not put a card with, replaying that deal
    would show the observer something different."""
    soak = load()
    monkeypatch.setattr(soak, "example_deal", lambda c, fixed: soak.new_game(1).hands)
    games, *_, failure = soak.check_range(5, 1, 1)
    assert games == 0
    assert "another deal changes" in failure


def test_no_deal_for_a_named_seat_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    soak = load()
    monkeypatch.setattr(soak, "example_deal", lambda c, fixed: None)
    *_, failure = soak.check_range(5, 1, 1)
    assert "no deal puts card" in failure


def test_a_certain_miss_that_hits_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    soak = load()
    hit = soak.AskEvent(number=0, asker=0, target=3, card=0, success=True)
    monkeypatch.setattr(soak, "certain_misses", lambda start, actions: (hit,))
    *_, failure = soak.check_range(5, 1, 1000)
    assert failure == "5: DeductionError: a certain miss succeeded"


def test_a_failure_makes_the_run_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    soak = load()
    monkeypatch.setattr(
        soak, "check_range", lambda first, count, probe: (0, 0, 0, 0, f"{first}: x")
    )
    monkeypatch.setattr(soak, "ProcessPoolExecutor", _InProcess)
    out = tmp_path / "soak.json"
    assert soak.main(["--games", "4", "--chunk", "2", "--json", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["first_failure"] == "0: x"


def test_the_soak_rejects_zero_games() -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--games", "0"], capture_output=True, text=True
    )
    assert run.returncode == 2


class _InProcess:
    """Stands in for the process pool, so a patched function is the one that runs."""

    def __init__(self, max_workers: int) -> None:
        self.workers = max_workers

    def __enter__(self) -> _InProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def map(
        self, function: Callable[..., object], *iterables: Iterable[object]
    ) -> Iterator[object]:
        return map(function, *iterables, strict=True)
