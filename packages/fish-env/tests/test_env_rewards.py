"""Tests for how an environment game ends: the reward is the result (R.7.1), given once at the
end and zero-sum between the teams; a game stopped at 1,000 asks (R.8.2) truncates every
agent with no reward."""

from dataclasses import replace

import numpy as np
import pytest

from fish_env import AGENTS, FishEnv
from fish_env.env import LOSS_REWARD, WIN_REWARD, seat_of
from fish_rules.action_index import CALL_BASE, PASS_INDEX
from fish_rules.cards import team_of
from fish_rules.state import MAX_ASKS, Outcome, Phase


def play_to_the_end(game: FishEnv, policy_seed: int) -> dict[str, float]:
    """Play randomly to the end. Checks that every step before the end rewards nothing, and
    returns the reward each agent sees when its episode is over."""
    rng = np.random.default_rng(policy_seed)
    final: dict[str, float] = {}
    for agent in game.agent_iter():
        observation, reward, terminated, truncated, _ = game.last()
        if terminated or truncated:
            final[agent] = float(reward)
            game.step(None)
            continue
        assert reward == 0
        assert observation is not None
        game.step(int(rng.choice(np.flatnonzero(observation["action_mask"]))))
        if game.game.phase is not Phase.OVER:
            assert all(value == 0 for value in game.rewards.values())
    return final


@pytest.mark.parametrize("policy_seed", range(8))
def test_r7_1_the_winning_team_gets_one_and_the_other_minus_one(policy_seed: int) -> None:
    """R.7.1: the team that claims five sets wins. Every seat of it is rewarded +1 and every
    seat of the other team -1, once, when the game ends; the rewards sum to zero."""
    game = FishEnv()
    game.reset(seed=500 + policy_seed)
    rng = np.random.default_rng(policy_seed)
    while game.game.phase is not Phase.OVER:
        mask = game.observe(game.agent_selection)["action_mask"]
        game.step(int(rng.choice(np.flatnonzero(mask))))
    winner = game.game.winner()
    assert game.game.outcome is Outcome.FINISHED
    assert winner is not None
    assert game.terminations == dict.fromkeys(AGENTS, True)
    assert not any(game.truncations.values())
    assert game.infos == {agent: {"outcome": "finished", "winner": winner} for agent in AGENTS}
    final = play_to_the_end(game, policy_seed)
    assert final == {
        agent: WIN_REWARD if team_of(seat_of(agent)) == winner else LOSS_REWARD for agent in AGENTS
    }
    assert sum(final.values()) == 0
    assert game.agents == []


@pytest.mark.parametrize("policy_seed", range(8))
def test_rewards_are_given_only_at_the_end(policy_seed: int) -> None:
    game = FishEnv()
    game.reset(seed=700 + policy_seed)
    final = play_to_the_end(game, policy_seed)
    assert sorted(final.values()) == [LOSS_REWARD] * 3 + [WIN_REWARD] * 3


def test_r8_2_a_game_stopped_at_the_ask_limit_is_truncated_without_reward() -> None:
    """R.8.2: a game that reaches 1,000 asks ends unfinished. It has no result, so every
    agent is truncated, not terminated, and rewarded 0."""
    game = FishEnv()
    game.reset(seed=42)
    for _ in AGENTS:
        game.step(PASS_INDEX)
    assert game.game.phase is Phase.TURN
    game._game = replace(game.game, asks=MAX_ASKS - 1)  # pyright: ignore[reportPrivateUsage]
    mask = game.observe(game.agent_selection)["action_mask"]
    asks = np.flatnonzero(mask[:CALL_BASE])
    assert asks.size > 0
    game.step(int(asks[0]))
    assert game.game.outcome is Outcome.UNFINISHED
    assert game.truncations == dict.fromkeys(AGENTS, True)
    assert not any(game.terminations.values())
    assert game.rewards == dict.fromkeys(AGENTS, 0.0)
    assert game.infos == {agent: {"outcome": "unfinished", "winner": None} for agent in AGENTS}
    for agent in game.agent_iter():
        _, reward, terminated, truncated, _ = game.last()
        assert (reward, terminated, truncated) == (0, False, True)
        assert agent in AGENTS
        game.step(None)
    assert game.agents == []
