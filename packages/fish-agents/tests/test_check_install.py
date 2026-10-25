"""The install check (scripts/check_install.py) finds every Python block in the READMEs. The
check itself builds the packages, installs them from PyPI into a clean environment and runs
that code; it needs the network, so CI runs it as its own job."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "check_install.py"


def test_it_runs_every_python_block_of_every_readme() -> None:
    listed = subprocess.run(
        [sys.executable, str(SCRIPT), "--list"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    expected = ["README.md", *(f"packages/{p}/README.md" for p in ("fish-rules", "fish-env",
                                                                   "fish-agents"))]  # fmt: skip
    for readme in expected:
        blocks = (ROOT / readme).read_text(encoding="utf-8").count("```python\n")
        assert blocks >= 1, readme
        assert [line for line in listed if line.startswith(f"{readme} block")] == [
            f"{readme} block {n}" for n in range(1, blocks + 1)
        ]
    examples = sorted(p.name for p in (ROOT / "examples").glob("*.py"))
    assert [line for line in listed if line.startswith("examples/")] == [
        f"examples/{name}" for name in examples
    ]
