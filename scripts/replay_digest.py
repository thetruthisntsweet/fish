"""Replay digest (T2.5): one hash over the replays of a fixed set of games, compared across
processes, hash seeds and commits.

Run: ``uv run python scripts/replay_digest.py --check
packages/fish-agents/tests/vectors/replay_digest_v1.json``.

Plays ``--games`` games of each kind from seeds 0, 1, 2, ...:

- ``playout``: ``fish_rules.playout.random_game`` under environment mechanics, policy seed
  equal to the game seed;
- ``b0``: six B0 agents in the environment (``fish_agents.play.play_game``, b0-v1);
- ``website``: website mechanics (``website_game`` below): Call presses on any turn, windows
  closed whoever has answered, assignment and choice timeouts, and random legal seat actions,
  up to ``MAX_ACTIONS`` actions.

Every game goes through its log: the game record (``fish_rules.record``) is written to JSON
text, read back and replayed. The replay must give the same records and states as playing
did (for B0, the same final state as the environment), and ``replay_record`` must accept it.
A game's digest is the SHA-256 of its record's JSON and the state hash after every action;
each kind's digest covers its games' digests in seed order, and the digest covers the kinds.

Prints a short Markdown table. ``--out`` writes the result as JSON (it refuses to overwrite
a file); ``--check`` compares it with a frozen result and exits 1 if anything differs. CI
runs it under two hash seeds and compares the outputs (Implementation Environment §6). The
frozen digest changes only with the ruleset, the action or state encoding, or B0's version:
regenerate it together with the golden replays, and say so in the decision log.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from fish_agents.b0 import B0, B0_VERSION
from fish_agents.play import play_game
from fish_rules.action_index import decode, legal_indices
from fish_rules.codec import ACTION_ENCODING, action_from_data
from fish_rules.engine import acting_seats, apply, replay
from fish_rules.events import (
    Action,
    AssignTimeout,
    ChoiceTimeout,
    CloseWindow,
    OpenWindow,
    Record,
)
from fish_rules.playout import random_game
from fish_rules.record import game_record, replay_record
from fish_rules.rng import SplitMix64
from fish_rules.state import STATE_ENCODING, Phase, State, new_game, state_hash
from fish_rules.version import RULESET_VERSION

DIGEST_ENCODING: Final = "fish-replay-digest-v1"

MAX_ACTIONS: Final = 2_000
"""A website game stops here if it has not ended; its record then has no outcome."""

CONTROL_ODDS: Final = 4
"""In a website game, a control action (press, close, timeout) comes 1 time in this many
when one is available and a seat could act instead."""

CONTROL: Final[dict[Phase, Action]] = {
    Phase.TURN: OpenWindow(),
    Phase.WINDOW: CloseWindow(),
    Phase.ASSIGN: AssignTimeout(),
    Phase.CHOOSE: ChoiceTimeout(),
    Phase.VOTE: ChoiceTimeout(),
}

Played = tuple[dict[str, object], list[tuple[str, tuple[Record, ...]]] | None]
"""A game's record and, when it was played here, the state hash and records of every step."""


class DigestError(Exception):
    """A game's log did not replay to the game that was played."""


def website_game(game_seed: int, policy_seed: int) -> tuple[Action, ...]:
    """The actions of one game under website mechanics (R.4.3, R.5.2, R.8.3)."""
    rng = SplitMix64(policy_seed)
    state = new_game(game_seed)
    actions: list[Action] = []
    while state.phase is not Phase.OVER and len(actions) < MAX_ACTIONS:
        control = CONTROL.get(state.phase)
        seats = acting_seats(state)
        if control is not None and (not seats or rng.below(CONTROL_ODDS) == 0):
            action = control
        else:
            seat = rng.choice(seats)
            action = decode(seat, rng.choice(legal_indices(state, seat)), state.phase)
        state, _ = apply(state, action)
        actions.append(action)
    return tuple(actions)


def played_here(game_seed: int, actions: tuple[Action, ...]) -> Played:
    state: State = new_game(game_seed)
    steps: list[tuple[str, tuple[Record, ...]]] = []
    for action in actions:
        state, records = apply(state, action)
        steps.append((state_hash(state), records))
    return game_record(game_seed, actions, state), steps


KINDS: Final[dict[str, Callable[[int], Played]]] = {
    "playout": lambda seed: played_here(seed, random_game(seed, seed)),
    "b0": lambda seed: (play_game([B0()] * 6, seed), None),
    "website": lambda seed: played_here(seed, website_game(seed, seed)),
}


def game_digest(kind: str, seed: int) -> tuple[str, int, bool]:
    """The digest of one game, its number of actions, and whether it ended."""
    record, played = KINDS[kind](seed)
    text = json.dumps(record, sort_keys=True, separators=(",", ":"))
    data = json.loads(text)
    actions = [action_from_data(item) for item in data["actions"]]
    replayed = [(state_hash(s), r) for s, r in replay(int(data["seed"]), actions)]
    hashes = [h for h, _ in replayed]
    final = state_hash(replay_record(data))
    if hashes and hashes[-1] != final:
        raise DigestError(f"{kind} game {seed}: replay_record ends in another state")
    if played is not None and replayed != played:
        pairs = zip(replayed, played, strict=False)
        step = next((i for i, (a, b) in enumerate(pairs) if a != b), len(played))
        raise DigestError(f"{kind} game {seed}: the replay differs after action {step}")
    lines = [text, *hashes]
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest, len(actions), data["outcome"] is not None


def compute(games: int) -> dict[str, object]:
    kinds: dict[str, object] = {}
    for kind in KINDS:
        digests: list[str] = []
        actions = ended = 0
        for seed in range(games):
            digest, length, over = game_digest(kind, seed)
            digests.append(digest)
            actions += length
            ended += over
        kinds[kind] = {
            "actions": actions,
            "ended": ended,
            "digest": hashlib.sha256("\n".join(digests).encode("ascii")).hexdigest(),
        }
    total = "\n".join(f"{k}:{v['digest']}" for k, v in kinds.items())  # pyright: ignore[reportIndexIssue, reportUnknownMemberType]
    return {
        "encoding": DIGEST_ENCODING,
        "ruleset": RULESET_VERSION,
        "action_encoding": ACTION_ENCODING,
        "state_encoding": STATE_ENCODING,
        "agent": B0_VERSION,
        "games_per_kind": games,
        "kinds": kinds,
        "digest": hashlib.sha256(total.encode("ascii")).hexdigest(),
    }


def differences(result: dict[str, Any], frozen: dict[str, Any]) -> list[str]:
    """What differs, field by field, and kind by kind for the games."""
    found: list[str] = []
    for key in sorted(set(result) | set(frozen)):
        now, then = result.get(key), frozen.get(key)
        if key == "kinds" and isinstance(now, dict) and isinstance(then, dict):
            for kind in sorted(set(now) | set(then)):  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
                if now.get(kind) != then.get(kind):  # pyright: ignore[reportUnknownMemberType]
                    found.append(f"{kind} games: frozen {then.get(kind)}, now {now.get(kind)}")  # pyright: ignore[reportUnknownMemberType]
        elif now != then:
            found.append(f"{key}: frozen {then!r}, now {now!r}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hash the replays of a fixed set of games.")
    parser.add_argument("--games", type=int, default=100, help="games of each kind")
    parser.add_argument("--out", type=Path, help="write the result here (a new file)")
    parser.add_argument("--check", type=Path, help="compare with this frozen result")
    args = parser.parse_args(argv)
    if args.games < 1:
        parser.error("--games must be at least 1")
    if args.out is not None and args.out.exists():
        parser.error(f"{args.out} exists; refusing to overwrite it")

    try:
        result = compute(args.games)
    except DigestError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("| Kind | Actions | Ended | Digest |\n|---|---|---|---|")
    for kind, summary in result["kinds"].items():  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        print(f"| {kind} | {summary['actions']} | {summary['ended']} | `{summary['digest']}` |")
    print(f"| all | | | `{result['digest']}` |")
    if args.out is not None:
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.check is not None:
        frozen = json.loads(args.check.read_text(encoding="utf-8"))
        found = differences(result, frozen)
        if found:
            print("FAIL the replays differ from the frozen digest:", file=sys.stderr)
            for line in found:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(f"\nMatches {args.check.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
