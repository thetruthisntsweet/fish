"""Check that a version tag matches what the repository says it releases (T2.6).

Run: ``python scripts/check_release.py v0.1.0 [--notes FILE]`` (standard library only).

A tag ``vX.Y.Z`` may be released only if fish-rules, fish-env and fish-agents are all at
version ``X.Y.Z`` in their ``pyproject.toml``, ``CHANGELOG.md`` has a ``## X.Y.Z (date)``
entry with something under it, and ``CITATION.cff`` names the same version and date. With
``--notes`` it writes that changelog entry, without its heading, to ``FILE``: the text of
the GitHub release. Exits 1 and says what does not match.
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = ("fish-rules", "fish-env", "fish-agents")
TAG = re.compile(r"v(\d+\.\d+\.\d+)")


class ReleaseError(Exception):
    """The tag and the repository disagree."""


def version_of(package: str, root: Path) -> str:
    text = (root / "packages" / package / "pyproject.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["project"]["version"])


def release_notes(tag: str, root: Path = ROOT) -> str:
    """The changelog entry for ``tag``, once every check passes."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ReleaseError(f"{tag!r} is not a release tag (vX.Y.Z)")
    version = match[1]
    for package in PUBLISHED:
        if version_of(package, root) != version:
            raise ReleaseError(f"{package} is at {version_of(package, root)}, the tag is {tag}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(
        rf"^## {re.escape(version)} \((\d{{4}}-\d{{2}}-\d{{2}})\)\n", changelog, re.M
    )
    if heading is None:
        raise ReleaseError(f"CHANGELOG.md has no '## {version} (YYYY-MM-DD)' entry")
    following = re.search(r"^## ", changelog[heading.end() :], re.M)
    notes = changelog[heading.end() : heading.end() + following.start() if following else None]
    if not notes.strip():
        raise ReleaseError(f"the CHANGELOG.md entry for {version} is empty")
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    if not re.search(rf"^version: {re.escape(version)}$", citation, re.M):
        raise ReleaseError(f"CITATION.cff does not name version {version}")
    if not re.search(rf'^date-released: "{heading[1]}"$', citation, re.M):
        raise ReleaseError(f"CITATION.cff's date-released is not {heading[1]}, the changelog's")
    return notes.strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a release tag against the repository.")
    parser.add_argument("tag", help="the tag, such as v0.1.0")
    parser.add_argument("--notes", type=Path, help="write the changelog entry to this file")
    args = parser.parse_args(argv)
    try:
        notes = release_notes(args.tag)
    except ReleaseError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    if args.notes is not None:
        args.notes.write_text(notes, encoding="utf-8")
    print(f"{args.tag}: {', '.join(PUBLISHED)} and the changelog and citation agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
