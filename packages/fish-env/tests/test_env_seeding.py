"""Tests for deterministic seeding and the game record: the same seed and the same agent
actions give the same game, and every environment game replays exactly from its record
(R.10.2, docs/determinism.md §8)."""

import json

import numpy as np
import pytest

from fish_env import FishEnv
from fish_rules.cards import deal, first_player
from fish_rules.engine import apply, replay
from fish_rules.events import OpenWindow
from fish_rules.record import replay_record
from fish_rules.state import new_game, state_hash
from fish_rules.version import RULESET_VERSION


def play(game_seed: int, policy_seed: int) -> tuple[FishEnv, list[int], list[str]]:
    """Play a whole game with random legal actions. Returns the environment, the index each
    agent chose, and the state hash after every agent step."""
    game = FishEnv()
    game.reset(seed=game_seed)
    rng = np.random.default_rng(policy_seed)
    chosen: list[int] = []
    hashes: list[str] = []
    for agent in game.agent_iter():
        _, _, terminated, truncated, _ = game.last()
        if terminated or truncated:
            game.step(None)
            continue
        index = int(rng.choice(np.flatnonzero(game.observe(agent)["action_mask"])))
        chosen.append(index)
        game.step(index)
        hashes.append(game.state_hash())
    return game, chosen, hashes


def test_the_seed_alone_decides_the_deal_and_first_player() -> None:
    game = FishEnv()
    game.reset(seed=2026)
    assert game.game.hands == deal(2026)
    assert game.game.current == first_player(2026)
    assert game.game == apply(new_game(2026), OpenWindow())[0]


@pytest.mark.parametrize(("game_seed", "policy_seed"), [(0, 0), (77, 3), (2**64 - 1, 9)])
def test_same_seed_and_actions_give_the_same_game(game_seed: int, policy_seed: int) -> None:
    first, chosen, hashes = play(game_seed, policy_seed)
    second = FishEnv()
    second.reset(seed=game_seed)
    replayed: list[str] = []
    for index in chosen:
        second.step(index)
        replayed.append(second.state_hash())
    assert replayed == hashes
    assert second.record() == first.record()


def test_different_seeds_give_different_games() -> None:
    hashes = set()
    for seed in range(20):
        game = FishEnv()
        game.reset(seed=seed)
        hashes.add(game.state_hash())
    assert len(hashes) == 20


@pytest.mark.parametrize("policy_seed", range(6))
def test_r10_2_the_record_replays_exactly(policy_seed: int) -> None:
    """R.10.2: the record carries the ruleset version; seed plus actions reproduce the game,
    through JSON and back."""
    game, _, _ = play(9000 + policy_seed, policy_seed)
    record = json.loads(json.dumps(game.record()))
    assert record["ruleset"] == RULESET_VERSION
    assert record["seed"] == str(game.game_seed)
    assert record["outcome"] == str(game.game.outcome)
    assert state_hash(replay_record(record)) == game.state_hash()
    *_, (final, _) = replay(int(record["seed"]), game.actions)
    assert state_hash(final) == game.state_hash()


def test_a_record_mid_game_replays_to_the_same_point() -> None:
    game = FishEnv()
    game.reset(seed=31)
    for _ in range(20):
        mask = game.observe(game.agent_selection)["action_mask"]
        game.step(int(np.flatnonzero(mask)[0]))
    record = game.record()
    assert record["outcome"] is None
    assert state_hash(replay_record(record)) == game.state_hash()


def test_an_unseeded_game_records_its_seed() -> None:
    game = FishEnv()
    game.reset()
    assert game.game_seed is not None
    assert game.record()["seed"] == str(game.game_seed)
    assert game.game.hands == deal(game.game_seed)


def test_reset_takes_no_options() -> None:
    game = FishEnv()
    game.reset(seed=1, options={})
    with pytest.raises(ValueError, match="no reset options"):
        game.reset(seed=1, options={"memory": "full"})


def test_record_needs_a_reset() -> None:
    with pytest.raises(RuntimeError, match="reset"):
        FishEnv().record()
