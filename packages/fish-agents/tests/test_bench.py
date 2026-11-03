"""The performance smoke script (scripts/bench_b0.py) runs and writes every number CI keeps,
for B0 and for B1."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts" / "bench_b0.py"


def test_bench_writes_its_numbers(tmp_path: Path) -> None:
    out = tmp_path / "performance.json"
    args = ["--games", "3", "--mask-games", "1", "--deduce-games", "1", "--b1-games", "1"]
    args += ["--json", str(out)]
    run = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=True
    )
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["agent"] == "b0-v1"
    assert result["games"] == 3
    assert result["unfinished"] == 0
    assert result["games_per_second"] > 0
    assert result["mask_microseconds"] > 0
    assert result["deduce_microseconds"] > 0
    assert result["deduce_p99_microseconds"] > 0
    assert result["deductions_timed"] > 0
    assert result["mean_asks"] > 0
    assert result["b1_agent"] == "b1-v1"
    assert result["b1_games"] == 1
    assert result["b1_unfinished"] == 0  # seed 0 at full memory finishes
    assert result["b1_games_per_second"] > 0
    assert 0 < result["b1_decision_microseconds"] <= result["b1_decision_p99_microseconds"]
    assert 0 < result["b1_decisions_timed"] < result["b1_mean_actions"]  # windows open and close
    assert "| games_per_second |" in run.stdout
    assert "| b1_decision_microseconds |" in run.stdout


def test_bench_rejects_zero_games() -> None:
    for flag in ("--games", "--b1-games"):
        run = subprocess.run(
            [sys.executable, str(SCRIPT), flag, "0"], capture_output=True, text=True
        )
        assert run.returncode == 2
        assert "at least 1" in run.stderr
