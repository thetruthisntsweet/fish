"""Install the published packages the way a stranger would, and run their documentation (T2.6).

Run: ``uv run --no-project --python 3.14 python scripts/check_install.py`` (it needs only the
standard library, uv and the network). With ``--list`` it only prints what it would run. With
``--dist DIR`` it keeps the built files in ``DIR``, a new folder: these checked files are the
ones the release uploads (``.github/workflows/release.yml``).

1. Builds fish-rules, fish-env and fish-agents (``uv build``: a source archive, then a wheel
   built from that archive, so both are known to work) into a temporary folder, and checks
   them with ``twine check``.
2. Creates an empty virtual environment outside the repository and installs the three wheels
   into it, with ``fish-agents[env]``; everything else comes from PyPI, exactly as for a user.
3. Checks that every package imports from that environment, not from the repository, at the
   version in its ``pyproject.toml``, and that ``pip check`` finds no broken dependency.
4. Runs, in that environment and from an empty folder, every Python code block in
   ``README.md`` and in each package's ``README.md`` (the text PyPI shows), and every script in
   ``examples/``. Each must exit cleanly.

Exits 1 and says which step failed. CI runs it in the *Install from the built packages* job.
"""

import argparse
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = ("fish-rules", "fish-env", "fish-agents")
TWINE = "twine>=7,<8"
"""The twine release that checks the files, as PyPI's upload will."""
PYTHON_BLOCK = re.compile(r"^```python\n(.*?)^```$", re.MULTILINE | re.DOTALL)


class CheckError(Exception):
    """One step of the check failed."""


def version_of(package: str) -> str:
    text = (ROOT / "packages" / package / "pyproject.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["project"]["version"])


def documented_code() -> list[tuple[str, str]]:
    """(where, code) for every Python block in the READMEs and every example script."""
    found: list[tuple[str, str]] = []
    readmes = [ROOT / "README.md", *(ROOT / "packages" / p / "README.md" for p in PUBLISHED)]
    for readme in readmes:
        for number, code in enumerate(PYTHON_BLOCK.findall(readme.read_text("utf-8")), 1):
            found.append((f"{readme.relative_to(ROOT)} block {number}", code))
    for example in sorted((ROOT / "examples").glob("*.py")):
        found.append((str(example.relative_to(ROOT)), example.read_text("utf-8")))
    return found


def run(command: list[str], what: str, cwd: Path | None = None) -> str:
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise CheckError(f"{what}:\n{done.stdout}{done.stderr}")
    return done.stdout


def check(work: Path, dist: Path | None = None) -> int:
    dist = dist or work / "dist"
    venv, empty = work / "venv", work / "empty"
    empty.mkdir()
    for package in PUBLISHED:
        run(["uv", "build", "--package", package, "--out-dir", str(dist)], f"building {package}",
            cwd=ROOT)  # fmt: skip
    built = sorted([*dist.glob("*.whl"), *dist.glob("*.tar.gz")])
    if len(built) != 2 * len(PUBLISHED):
        raise CheckError(f"expected a wheel and a source archive per package, got {built}")
    run(["uvx", "--from", TWINE, "twine", "check", "--strict", *map(str, built)], "twine check")
    print(f"built and checked {len(built)} files")

    run(["uv", "venv", "--python", "3.14", str(venv)], "creating the environment")
    python = venv / "bin" / "python"
    wheels = {p: next(dist.glob(f"{p.replace('-', '_')}-*.whl")) for p in PUBLISHED}
    targets = [str(wheels["fish-rules"]), str(wheels["fish-env"]), f"{wheels['fish-agents']}[env]"]
    run(["uv", "pip", "install", "--python", str(python), *targets], "installing the wheels")
    run(["uv", "pip", "check", "--python", str(python)], "pip check")

    for package in PUBLISHED:
        module = package.replace("-", "_")
        probe = f"import {module} as m; print(m.__version__); print(m.__file__)"
        version, location = run([str(python), "-I", "-c", probe], f"importing {module}",
                                cwd=empty).split()  # fmt: skip
        if version != version_of(package):
            raise CheckError(f"{module} is {version}, expected {version_of(package)}")
        if not Path(location).is_relative_to(venv):
            raise CheckError(f"{module} was imported from {location}, not the environment")
    print(f"installed {', '.join(f'{p} {version_of(p)}' for p in PUBLISHED)}")

    for where, code in documented_code():
        script = empty / "snippet.py"
        script.write_text(code, encoding="utf-8")
        run([str(python), "-I", str(script)], f"running {where}", cwd=empty)
        print(f"ran {where}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the built packages and run the docs.")
    parser.add_argument("--list", action="store_true", help="only list the code that would run")
    parser.add_argument("--dist", type=Path, help="a new folder to keep the built files in")
    args = parser.parse_args(argv)
    if args.dist is not None and args.dist.exists():
        parser.error(f"{args.dist} exists; the built files go into a new folder")
    if args.list:
        for where, _ in documented_code():
            print(where)
        return 0
    with tempfile.TemporaryDirectory(prefix="fish-install-") as work:
        try:
            return check(Path(work), args.dist and args.dist.resolve())
        except CheckError as error:
            print(f"FAIL {error}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
