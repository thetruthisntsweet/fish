"""Golden replays (Implementation Environment §6, §9): complete games stored as seed plus
actions, with the state hash after every action. Replaying each must give exactly the same
states. Written once by ``scripts/make_golden_games.py``; a failure here means the rules now
play differently, which needs a new ruleset version (R.10), not new golden files."""

import json
from pathlib import Path
from typing import Any

import pytest

from fish_rules.codec import ACTION_ENCODING, action_from_data
from fish_rules.engine import replay
from fish_rules.state import STATE_ENCODING, Outcome, check_consistency, state_hash
from fish_rules.version import RULESET_VERSION

GOLDEN = sorted((Path(__file__).parent / "golden").glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_golden_set_covers_every_feature() -> None:
    assert [path.stem for path in GOLDEN] == [
        "call_on_turn",
        "caller_chooses",
        "discarded_declaration",
        "runout",
        "seed_tiebreak",
        "team_0_wins",
        "team_1_wins",
        "team_votes",
    ]


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_r10_2_golden_game_replays_exactly(path: Path) -> None:
    """R.10.2: every game record carries the ruleset version it was played under. A game is
    its seed plus its actions (docs/determinism.md §8); replay must give the same state after
    every action, forever."""
    game = load(path)
    assert game["ruleset"] == RULESET_VERSION
    assert game["state_encoding"] == STATE_ENCODING
    assert game["action_encoding"] == ACTION_ENCODING
    actions = [action_from_data(data) for data in game["actions"]]
    assert len(actions) == len(game["hashes"])
    state = None
    for step, ((state, _), expected) in enumerate(
        zip(replay(int(game["seed"]), actions), game["hashes"], strict=True)
    ):
        assert state_hash(state) == expected, f"state differs after action {step}"
        check_consistency(state)
    assert state is not None
    assert state.outcome is Outcome(game["outcome"])
    assert state.winner() == game["winner"]
