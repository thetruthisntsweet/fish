"""The performance smoke script (scripts/bench_b0.py) runs and writes every number CI keeps."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts" / "bench_b0.py"


def test_bench_writes_its_numbers(tmp_path: Path) -> None:
    out = tmp_path / "performance.json"
    args = ["--games", "3", "--mask-games", "1", "--deduce-games", "1", "--json", str(out)]
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
    assert "| games_per_second |" in run.stdout


def test_bench_rejects_zero_games() -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--games", "0"], capture_output=True, text=True
    )
    assert run.returncode == 2
    assert "at least 1" in run.stderr
