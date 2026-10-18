"""The README's quick start runs as written, so the documented usage cannot drift from the
environment."""

import contextlib
import io
import re
from pathlib import Path

README = Path(__file__).parents[3] / "README.md"


def python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)


def test_readme_has_one_example() -> None:
    assert len(python_blocks(README.read_text(encoding="utf-8"))) == 1


def test_readme_example_runs() -> None:
    (code,) = python_blocks(README.read_text(encoding="utf-8"))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(code, str(README), "exec"), {"__name__": "readme"})
    assert re.fullmatch(r"winner: team [01]\n", output.getvalue())
