"""Write the golden replays in packages/fish-rules/tests/golden/ (T2.2 subtask 9).

Each file is one complete game: its seed, its actions and the state hash after every action.
``tests/test_golden.py`` replays them on every run, so any change to how the rules play out,
however small, fails CI.

Games come from ``fish_rules.playout.random_game``. The script walks (game seed, policy seed)
pairs in order and keeps the first game showing each feature below (one game per feature), so
the set covers every phase and record type and both teams winning.

Run once: ``uv run python scripts/make_golden_games.py``. It refuses to overwrite existing
files. Regenerate (``--regenerate``) only together with a new ruleset version or a new
``STATE_ENCODING``, and say so in the decision log: a golden game that changes is a rule that
changed.
"""

import json
import sys
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

from fish_rules.codec import ACTION_ENCODING, action_to_data
from fish_rules.engine import replay
from fish_rules.events import (
    Action,
    CallEvent,
    ChoiceEvent,
    DeclarationDiscarded,
    GameOver,
    Record,
    RunoutCallerSelected,
    SeedChose,
    VoteCast,
)
from fish_rules.playout import random_game
from fish_rules.state import STATE_ENCODING, CallSource, Outcome, state_hash
from fish_rules.version import RULESET_VERSION

OUT = Path(__file__).resolve().parent.parent / "packages/fish-rules/tests/golden"

type Feature = Callable[[list[Record]], bool]

FEATURES: dict[str, Feature] = {
    "runout": lambda rs: any(isinstance(r, RunoutCallerSelected) for r in rs),
    "seed_tiebreak": lambda rs: any(isinstance(r, SeedChose) for r in rs),
    "discarded_declaration": lambda rs: any(isinstance(r, DeclarationDiscarded) for r in rs),
    "call_on_turn": lambda rs: any(
        isinstance(r, CallEvent) and r.source is CallSource.TURN for r in rs
    ),
    "caller_chooses": lambda rs: any(
        isinstance(a, CallEvent) and a.correct and isinstance(b, ChoiceEvent)
        for a, b in pairwise(rs)
    ),
    "team_votes": lambda rs: any(isinstance(r, VoteCast) for r in rs),
    "team_0_wins": lambda rs: GameOver(Outcome.FINISHED, 0) in rs,
    "team_1_wins": lambda rs: GameOver(Outcome.FINISHED, 1) in rs,
}


def describe(seed: int, policy: int, actions: tuple[Action, ...]) -> dict[str, object]:
    hashes: list[str] = []
    outcome, winner = None, None
    for state, _ in replay(seed, actions):
        hashes.append(state_hash(state))
        outcome, winner = state.outcome, state.winner()
    assert outcome is Outcome.FINISHED
    return {
        "ruleset": RULESET_VERSION,
        "state_encoding": STATE_ENCODING,
        "action_encoding": ACTION_ENCODING,
        "seed": str(seed),
        "policy_seed": str(policy),
        "outcome": outcome.value,
        "winner": winner,
        "actions": [action_to_data(action) for action in actions],
        "hashes": hashes,
    }


def main() -> None:
    regenerate = "--regenerate" in sys.argv[1:]
    if OUT.exists() and any(OUT.iterdir()) and not regenerate:
        sys.exit(f"{OUT} already has golden games. Regenerate only with a new ruleset version.")
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = dict(FEATURES)
    seed = 0
    while wanted:
        policy = 1_000 + seed
        actions = random_game(seed, policy)
        records = [r for _, step in replay(seed, actions) for r in step]
        for name, has in list(wanted.items()):
            if has(records):
                game = describe(seed, policy, actions)
                path = OUT / f"{name}.json"
                path.write_text(json.dumps(game, separators=(",", ":")) + "\n", encoding="utf-8")
                print(f"wrote {path.name}: seed {seed}, {len(actions)} actions")
                del wanted[name]
                break
        seed += 1


if __name__ == "__main__":
    main()
