"""Check a copy of the corpus export (T3.6; docs/runbooks/backups.md): that every line is a
``fish-corpus-v2`` record that reads and replays, how many games it holds, and its SHA-256,
to compare with what the export printed on the server.

    uv run python scripts/check_export.py ~/FishBackups/corpus-2026-12-14.jsonl.gz

Reads gzipped (``.gz``) or plain JSON Lines. Prints the games, the people, the file's size
and SHA-256, and PASS; or FAIL with the first line that does not read, and exits 1.
"""

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import IO

from fish_rules.corpus import read_corpus_record


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _open(path: Path) -> IO[str]:
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def check(path: Path) -> tuple[int, int]:
    """The games and the people in the export at ``path``; raises ValueError at the first
    line that is not a record that reads and replays, or a game id out of order."""
    games = 0
    people: set[str] = set()
    with _open(path) as file:
        for number, line in enumerate(file, start=1):
            try:
                game = read_corpus_record(json.loads(line))
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f"line {number}: {error}") from error
            games += 1
            if game.game.id != f"g-{games:06d}":
                raise ValueError(f"line {number}: game {game.game.id}, not g-{games:06d}")
            people |= {s.person for s in game.seats if s.person is not None}
    return games, len(people)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a copy of the corpus export.")
    parser.add_argument("export", type=Path, help="the copied file (.jsonl or .jsonl.gz)")
    args = parser.parse_args(argv)
    path: Path = args.export
    try:
        games, people = check(path)
    except (OSError, ValueError, EOFError) as error:  # EOFError: a gzip file cut short
        print(f"FAIL {path}: {error}")
        return 1
    print(f"exported: {games}")
    print(f"people: {people}")
    print(f"file: {path} ({path.stat().st_size:,} bytes)")
    print(f"sha256: {sha256(path)}")
    print("PASS: compare exported, people and sha256 with what the server printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
