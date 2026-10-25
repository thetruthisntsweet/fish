"""Every script in examples/ runs and exits cleanly (T2.6). CI also runs them against the
built packages in a clean environment (scripts/check_install.py)."""

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = sorted((Path(__file__).parents[3] / "examples").glob("*.py"))


def test_there_are_examples() -> None:
    assert [p.name for p in EXAMPLES] == [
        "01_random_game.py",
        "02_your_own_agent.py",
        "03_replay_and_inspect.py",
        "04_training_loop.py",
    ]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.stem)
def test_the_example_runs(example: Path, tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, str(example)], cwd=tmp_path, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip(), "an example says what it did"
    assert list(tmp_path.iterdir()) == [], "an example leaves no files behind"
