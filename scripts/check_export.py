"""Check a copy of the corpus export (T3.6; docs/runbooks/backups.md): that every line is a
``fish-corpus-v2`` record that reads and replays, how many games it holds, and its SHA-256,
to compare with what the export printed on the server.

    uv run python scripts/check_export.py ~/FishBackups/corpus-2026-12-14.jsonl.gz

Reads gzipped (``.gz``) or plain JSON Lines. Prints the games, the people, the file's size
and SHA-256, and PASS; or FAIL with the first line that does not read, and exits 1.

    uv run python scripts/check_export.py ~/FishBackups/corpus-2026-12-21.jsonl.gz \
        --previous ~/FishBackups/corpus-2026-12-14.jsonl.gz

With ``--previous`` (T4.4), it also checks that nothing already collected has changed: every
game in last week's copy is in this week's, the same in everything but what an export draws
afresh (its release id and its people's pseudonyms), with the same people in the same seats
across games. Two differences are allowed. A note-taking answer may have arrived since, for a
seat that was ``unanswered``. And games may be gone because a person withdrew: say how many
with ``--gone N``, from the rise in the server's "left out, a person withdrew" line. Any other
difference fails, naming the games by their seeds.
"""

import argparse
import gzip
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

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


@dataclass(frozen=True, slots=True)
class Stored:
    """What must stay the same about one game from export to export."""

    fingerprint: str
    """A hash of the record without its release id, pseudonyms and note answers."""
    people: tuple[str | None, ...]
    """Each seat's pseudonym in that export, or None for a bot."""
    notes: tuple[str | None, ...]


def stored(record: dict[str, Any]) -> tuple[int, Stored]:
    """A record's seed, and what must stay the same about it."""
    seats = record["seats"]
    plain = record | {
        "game": {k: v for k, v in record["game"].items() if k != "id"},
        "seats": [seat | {"person": seat["person"] is not None, "note": None} for seat in seats],
    }
    canonical = json.dumps(plain, sort_keys=True, separators=(",", ":"))
    return record["seed"], Stored(
        hashlib.sha256(canonical.encode()).hexdigest(),
        tuple(seat["person"] for seat in seats),
        tuple(seat["note"] for seat in seats),
    )


def _games(path: Path) -> dict[int, Stored]:
    with _open(path) as file:
        return dict(stored(json.loads(line)) for line in file)


@dataclass(frozen=True, slots=True)
class Continuity:
    kept: int
    new: int
    gone: int
    notes_added: int


def compare(previous: Path, current: Path, gone_expected: int = 0) -> Continuity:
    """Check that every game in ``previous`` is unchanged in ``current`` (see above). Raises
    ValueError saying what changed."""
    before, now = _games(previous), _games(current)
    problems: list[str] = []
    renamed: dict[str, str] = {}  # last week's pseudonym -> this week's
    taken: dict[str, str] = {}
    notes_added = 0
    for seed, new in now.items():  # in the file's order, so the same game is always named
        if seed not in before:
            continue
        old = before[seed]
        if old.fingerprint != new.fingerprint:
            problems.append(f"the game with seed {seed} has changed")
            continue
        for was, is_ in zip(old.people, new.people, strict=True):
            if was is None or is_ is None:
                continue
            if renamed.setdefault(was, is_) != is_ or taken.setdefault(is_, was) != was:
                problems.append(f"the game with seed {seed} seats a different person")
                break
        for was, is_ in zip(old.notes, new.notes, strict=True):
            if was != is_:
                if was != "unanswered":
                    problems.append(
                        f"the game with seed {seed} has a note answer changed from {was}"
                    )
                else:
                    notes_added += 1
    gone = sorted(before.keys() - now.keys())
    if len(gone) != gone_expected:
        seeds = ", ".join(str(seed) for seed in gone[:10]) or "none"
        problems.append(
            f"{len(gone)} games are gone since {previous.name}, not {gone_expected} (seeds:"
            f" {seeds}). Games go only when a person withdraws: compare with the server's"
            ' "left out, a person withdrew", and pass --gone'
        )
    if problems:
        more = f"; and {len(problems) - 5} more" if len(problems) > 5 else ""
        raise ValueError("; ".join(problems[:5]) + more)
    return Continuity(
        len(before) - len(gone), len(now.keys() - before.keys()), len(gone), notes_added
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a copy of the corpus export.")
    parser.add_argument("export", type=Path, help="the copied file (.jsonl or .jsonl.gz)")
    parser.add_argument("--previous", type=Path, help="last week's copy, to compare with")
    parser.add_argument("--gone", type=int, default=0, help="games withdrawn since --previous (0)")
    args = parser.parse_args(argv)
    path: Path = args.export
    previous: Path | None = args.previous
    if previous is None and args.gone:
        parser.error("--gone needs --previous")
    try:
        games, people = check(path)
        kept = None
        if previous is not None:
            check(previous)
            kept = compare(previous, path, args.gone)
    except (OSError, ValueError, EOFError) as error:  # EOFError: a gzip file cut short
        print(f"FAIL {path}: {error}")
        return 1
    print(f"exported: {games}")
    print(f"people: {people}")
    print(f"file: {path} ({path.stat().st_size:,} bytes)")
    print(f"sha256: {sha256(path)}")
    if kept is not None and previous is not None:
        print(
            f"since {previous.name}: {kept.kept} games unchanged, {kept.new} new,"
            f" {kept.gone} gone, {kept.notes_added} note answers added"
        )
    print("PASS: compare exported, people and sha256 with what the server printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
