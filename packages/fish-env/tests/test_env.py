"""Tests for fish_env.env: the AEC cycle, the control actions the environment applies itself
(R.4.2, R.8.9), observations and masks, and how bad input is rejected."""

import numpy as np
import pytest

from fish_env import AGENTS, FishEnv, env
from fish_env.env import seat_of
from fish_rules.action_index import NUM_ACTIONS, PASS_INDEX, legal_mask
from fish_rules.cards import SEATS
from fish_rules.engine import IllegalActionError, acting_seats, replay
from fish_rules.events import CloseWindow, OpenWindow, Pass
from fish_rules.state import Phase, state_hash


def play_randomly(game: FishEnv, policy_seed: int) -> int:
    """Play ``game`` to the end with uniformly random legal actions; return the agent steps.
    At every step the selected agent is the lowest seat that may act."""
    rng = np.random.default_rng(policy_seed)
    steps = 0
    for agent in game.agent_iter():
        observation, _, terminated, truncated, _ = game.last()
        if terminated or truncated:
            game.step(None)
            continue
        assert observation is not None
        assert seat_of(agent) == acting_seats(game.game)[0]
        assert game.game.phase is not Phase.OVER
        game.step(int(rng.choice(np.flatnonzero(observation["action_mask"]))))
        steps += 1
    return steps


# ---------------------------------------------------------------- reset


def test_r4_2_a_window_opens_before_the_first_turn() -> None:
    """R.4.2: a window opens before the first player acts; the lowest seat answers first."""
    game = FishEnv()
    game.reset(seed=42)
    assert game.game_seed == 42
    assert game.agents == list(AGENTS) == [f"seat_{seat}" for seat in SEATS]
    assert game.actions == (OpenWindow(),)
    assert game.game.phase is Phase.WINDOW
    assert game.agent_selection == "seat_0"


def test_observation_is_own_hand_and_mask() -> None:
    game = FishEnv()
    game.reset(seed=42)
    for agent in AGENTS:
        observation = game.observe(agent)
        seat = seat_of(agent)
        assert game.observation_space(agent).contains(observation)
        assert list(np.flatnonzero(observation["observation"])) == list(game.game.hands[seat])
        assert observation["action_mask"].tobytes() == legal_mask(game.game, seat)
        assert observation["action_mask"][PASS_INDEX] == 1
        assert game.action_space(agent).n == NUM_ACTIONS  # pyright: ignore[reportAttributeAccessIssue]


def test_reset_without_a_seed_draws_one() -> None:
    game = FishEnv()
    game.reset()
    first = game.game_seed
    game.reset()
    assert first is not None
    assert game.game_seed is not None
    assert 0 <= first < 2**64
    assert first != game.game_seed


def test_reset_accepts_numpy_integers() -> None:
    game = FishEnv()
    game.reset(seed=np.uint64(2**64 - 1))  # pyright: ignore[reportArgumentType]
    assert game.game_seed == 2**64 - 1
    assert type(game.game_seed) is int


@pytest.mark.parametrize("seed", [-1, 2**64])
def test_reset_rejects_seeds_out_of_range(seed: int) -> None:
    with pytest.raises(ValueError, match="2\\*\\*64"):
        FishEnv().reset(seed=seed)


def test_reset_rejects_seeds_that_are_not_integers() -> None:
    with pytest.raises(TypeError):
        FishEnv().reset(seed=1.5)  # pyright: ignore[reportArgumentType]


def test_reset_starts_over() -> None:
    game = FishEnv()
    game.reset(seed=3)
    play_randomly(game, 0)
    game.reset(seed=3)
    assert game.actions == (OpenWindow(),)
    assert game.agents == list(AGENTS)
    assert not any(game.terminations.values())


# ---------------------------------------------------------------- the cycle


def test_r8_9_window_closes_after_all_six_answer() -> None:
    """R.8.9: every agent is asked; the environment closes the window after the sixth."""
    game = FishEnv()
    game.reset(seed=42)
    current = game.game.current
    for agent in AGENTS:
        assert game.agent_selection == agent
        game.step(PASS_INDEX)
    assert game.actions == (OpenWindow(), *(Pass(seat) for seat in SEATS), CloseWindow())
    assert game.game.phase is Phase.TURN
    assert current is not None
    assert game.agent_selection == AGENTS[current]


@pytest.mark.parametrize("policy_seed", range(5))
def test_whole_game_ends_and_replays(policy_seed: int) -> None:
    """A random game reaches the end, every agent is removed by a dead step, and the seed
    plus the actions replay to the same final state."""
    game = FishEnv()
    game.reset(seed=1000 + policy_seed)
    assert play_randomly(game, policy_seed) > 0
    assert game.game.phase is Phase.OVER
    assert game.agents == []
    assert game.game_seed is not None
    *_, (final, _) = replay(game.game_seed, game.actions)
    assert state_hash(final) == state_hash(game.game)


# ---------------------------------------------------------------- bad input


def test_illegal_action_is_rejected_and_changes_nothing() -> None:
    game = FishEnv()
    game.reset(seed=42)
    before = (game.game, game.actions, game.agent_selection)
    with pytest.raises(IllegalActionError):
        game.step(0)  # an ask, during a window
    assert (game.game, game.actions, game.agent_selection) == before


def test_a_live_agent_must_act() -> None:
    game = FishEnv()
    game.reset(seed=42)
    with pytest.raises(ValueError, match="must choose"):
        game.step(None)


def test_a_finished_agent_may_only_pass_none() -> None:
    game = FishEnv()
    game.reset(seed=5)
    rng = np.random.default_rng(5)
    while not game.terminations[game.agent_selection]:
        mask = game.observe(game.agent_selection)["action_mask"]
        game.step(int(rng.choice(np.flatnonzero(mask))))
    with pytest.raises(ValueError, match="only valid action is None"):
        game.step(PASS_INDEX)


@pytest.mark.parametrize("index", [-1, NUM_ACTIONS])
def test_raw_env_rejects_indices_out_of_range(index: int) -> None:
    game = FishEnv()
    game.reset(seed=42)
    with pytest.raises(ValueError, match="range"):
        game.step(index)


def test_wrapped_env_checks_bounds_and_order() -> None:
    wrapped = env()
    with pytest.raises(AssertionError, match="reset"):
        wrapped.step(PASS_INDEX)
    wrapped.reset(seed=42)
    with pytest.raises(AssertionError):
        wrapped.step(NUM_ACTIONS)
    wrapped.step(PASS_INDEX)
    assert wrapped.agent_selection == "seat_1"


def test_the_game_needs_a_reset() -> None:
    with pytest.raises(RuntimeError, match="reset"):
        _ = FishEnv().game


def test_unknown_agent() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        seat_of("seat_6")


def test_no_render_modes() -> None:
    with pytest.raises(ValueError, match="no render modes"):
        FishEnv(render_mode="human")
    game = FishEnv()
    game.reset(seed=1)
    assert game.render() is None
    game.close()
    assert game.metadata["name"] == "fish_v0"
