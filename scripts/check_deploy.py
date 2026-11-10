"""Check that a tag may deploy the study's site (T4.3; .github/workflows/deploy.yml).

    python scripts/check_deploy.py site-2026.12.07 --commit 1234abc

A site tag is ``site-YYYY.MM.DD``, the day it is deployed (Eastern), with ``.2``, ``.3`` and
so on for a second or third that day: ``site-2026.12.07.2``. Its commit must be on main, so
nothing reaches the study's site that was not reviewed and merged. The workflow then checks
that CI passed on it. Exits 0 and prints OK, or 1 saying what is wrong.
"""

import argparse
import re
import subprocess
import sys
from datetime import date

TAG = re.compile(r"site-(\d{4})\.(\d{2})\.(\d{2})(?:\.([2-9]|[1-9]\d))?")


def check_tag(tag: str) -> date:
    """The day ``tag`` names. Raises ValueError if it is not a site tag."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"{tag!r} is not a site tag: site-YYYY.MM.DD, or site-YYYY.MM.DD.2 and on")
    year, month, day = (int(match.group(n)) for n in (1, 2, 3))
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError(f"{tag!r} names no real day") from None


def on_main(commit: str, main: str = "origin/main") -> bool:
    """Whether ``commit`` is ``main`` or one of its ancestors."""
    found = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, main], capture_output=True, check=False
    )
    if found.returncode > 1:
        raise ValueError(
            f"git cannot compare {commit} with {main}: {found.stderr.decode().strip()}"
        )
    return found.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that a tag may deploy the study's site.")
    parser.add_argument("tag")
    parser.add_argument("--commit", default="HEAD", help="the tagged commit (HEAD)")
    parser.add_argument("--main", default="origin/main", help="the main branch (origin/main)")
    args = parser.parse_args(argv)
    try:
        day = check_tag(args.tag)
        if not on_main(args.commit, args.main):
            raise ValueError(f"{args.tag}'s commit is not on main: merge it first")
    except ValueError as problem:
        print(f"FAIL: {problem}")
        return 1
    print(f"OK: {args.tag} ({day:%a} {day.day} {day:%b %Y}) is on main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
