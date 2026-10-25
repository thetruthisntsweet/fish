"""The nightly soak script (scripts/soak_b0.py) checks games in parallel and reports the first
seed that breaks an invariant."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts" / "soak_b0.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("soak_b0", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_soak_checks_games_on_two_workers(tmp_path: Path) -> None:
    out = tmp_path / "soak.json"
    args = ["--games", "12", "--workers", "2", "--chunk", "5", "--json", str(out)]
    run = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert (result["games_checked"], result["failures"], result["unfinished"]) == (12, 0, 0)
    assert result["mean_asks"] > 0
    assert "| games_checked | 12 |" in run.stdout


def test_a_broken_invariant_names_its_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    soak = load()

    def broken(state: object) -> None:
        raise ValueError("cards are not conserved")

    monkeypatch.setattr(soak, "check_consistency", broken)
    games, *_, failure = soak.check_range(40, 3)
    assert games == 0
    assert failure == "40: InvariantError: cards are not conserved"


def test_a_failure_makes_the_run_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    soak = load()
    monkeypatch.setattr(soak, "check_range", lambda first, count: (0, 0, 0, 0, f"{first}: boom"))
    monkeypatch.setattr(soak, "ProcessPoolExecutor", _InProcess)
    out = tmp_path / "soak.json"
    assert soak.main(["--games", "4", "--chunk", "2", "--json", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["first_failure"] == "0: boom"


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
