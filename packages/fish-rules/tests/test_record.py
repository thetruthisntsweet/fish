"""Tests for fish_rules.record: a game record is the ruleset version, the action encoding, the
seed and the actions (R.10.2, docs/determinism.md §8), and replaying it is exact."""

import json
from pathlib import Path
from typing import Any

import pytest

from fish_rules.codec import ACTION_ENCODING
from fish_rules.engine import IllegalActionError, replay
from fish_rules.events import Pass
from fish_rules.playout import random_game
from fish_rules.record import game_record, replay_record
from fish_rules.state import Outcome, new_game, state_hash
from fish_rules.version import RULESET_VERSION

GOLDEN = sorted((Path(__file__).parent / "golden").glob("*.json"))


def finished(game_seed: int, policy_seed: int) -> dict[str, object]:
    actions = random_game(game_seed, policy_seed)
    *_, (state, _) = replay(game_seed, actions)
    return game_record(game_seed, actions, state)


def test_r10_2_a_record_carries_the_ruleset_version() -> None:
    """R.10.2: every game record carries the ruleset version it was played under."""
    record = finished(3, 4)
    assert record["ruleset"] == RULESET_VERSION
    assert record["action_encoding"] == ACTION_ENCODING
    assert record["seed"] == "3"
    assert record["outcome"] == "finished"
    assert record["winner"] in (0, 1)
    assert json.loads(json.dumps(record)) == record


@pytest.mark.parametrize("seeds", [(0, 0), (1, 7), (2**64 - 1, 3), (12345, 99)])
def test_records_replay_exactly(seeds: tuple[int, int]) -> None:
    game_seed, policy_seed = seeds
    actions = random_game(game_seed, policy_seed)
    *_, (state, _) = replay(game_seed, actions)
    record = json.loads(json.dumps(game_record(game_seed, actions, state)))
    assert state_hash(replay_record(record)) == state_hash(state)


def test_a_game_in_progress_has_no_outcome() -> None:
    record = game_record(9, (), new_game(9))
    assert (record["outcome"], record["winner"], record["actions"]) == (None, None, [])
    assert replay_record(record) == new_game(9)


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_golden_games_are_records(path: Path) -> None:
    """The golden replays use the same keys; the extra ones are ignored."""
    golden: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert replay_record(golden).outcome is Outcome(golden["outcome"])


BAD: tuple[tuple[str, object, str], ...] = (
    ("ruleset", "1.0", "ruleset"),
    ("action_encoding", "fish-actions-v0", "action_encoding"),
    ("seed", 3, "decimal string"),
    ("seed", "-3", "decimal string"),
    ("seed", "٣", "decimal string"),
    ("seed", str(2**64), "2\\*\\*64"),
    ("actions", "OpenWindow", "list"),
    ("actions", ["OpenWindow"], "dict"),
    ("actions", [{"type": "Shout"}], "unknown action type"),
    ("outcome", "unfinished", "outcome"),
    ("outcome", None, "outcome"),
    ("winner", None, "winner"),
    ("winner", True, "winner"),
)


@pytest.mark.parametrize(("key", "value", "match"), BAD, ids=[f"{k}={v!r}" for k, v, _ in BAD])
def test_bad_records_are_rejected(key: str, value: object, match: str) -> None:
    record = finished(5, 6)
    record[key] = value
    with pytest.raises(ValueError, match=match):
        replay_record(record)


def test_wrong_winner_is_rejected() -> None:
    record = finished(5, 6)
    record["winner"] = 1 - int(record["winner"])  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match="winner"):
        replay_record(record)


def test_an_illegal_recorded_action_is_rejected() -> None:
    record = game_record(5, (Pass(0),), new_game(5))
    with pytest.raises(IllegalActionError):
        replay_record(record)
