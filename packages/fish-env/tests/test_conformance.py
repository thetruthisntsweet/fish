"""Conformance: the environment passes PettingZoo's own checks, plays exactly the mechanics
the golden games and the reference driver were made under (R.4.2, R.8.9), and keeps the rules'
invariants (R.9) at every agent step of random games."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pettingzoo.test import api_test, seed_test

from fish_env import FishEnv, env
from fish_env.env import AGENTS, seat_of
from fish_rules.action_index import encode
from fish_rules.codec import action_from_data
from fish_rules.engine import acting_seats
from fish_rules.events import Action, AssignTimeout, ChoiceTimeout, CloseWindow, OpenWindow
from fish_rules.playout import random_game
from fish_rules.state import Phase, check_consistency, state_hash

GOLDEN = sorted((Path(__file__).parents[2] / "fish-rules" / "tests" / "golden").glob("*.json"))
U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 10)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games are slower than single steps: a tenth of the profile's examples."""

# PettingZoo's api_test gives advice that does not fit a masked card game. It suggests Box or
# Discrete observation spaces and NumPy observations, but a dict of observation and action
# mask is its own convention for masked games (as in its classic environments). It warns on
# an all-zero observation, which is correct for a seat that holds no cards and may not act.
ADVISORY = (
    "ignore:Observation space for each agent probably should be:UserWarning",
    "ignore:Observation is not a NumPy array:UserWarning",
    "ignore:Observation numpy array is all zeros:UserWarning",
)


def feed(game: FishEnv, actions: tuple[Action, ...]) -> None:
    """Give ``game`` the seat actions of ``actions`` in order, skipping the control actions
    the environment applies itself."""
    for action in actions:
        if isinstance(action, OpenWindow | CloseWindow | AssignTimeout | ChoiceTimeout):
            continue
        assert seat_of(game.agent_selection) == action.seat
        game.step(encode(action))


# ---------------------------------------------------------------- PettingZoo's own checks


@pytest.mark.filterwarnings(*ADVISORY)
def test_pettingzoo_api_test_wrapped() -> None:
    api_test(env(), num_cycles=2_000)


@pytest.mark.filterwarnings(*ADVISORY)
def test_pettingzoo_api_test_raw() -> None:
    api_test(FishEnv(), num_cycles=2_000)


def test_pettingzoo_seed_test() -> None:
    seed_test(env, num_cycles=2_000)


# ---------------------------------------------------------------- the same mechanics


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_r8_9_env_applies_the_reference_mechanics(game_seed: int, policy_seed: int) -> None:
    """R.4.2, R.8.9: given the seat actions of a reference game, the environment opens and
    closes exactly the same windows, so its action log is the reference game's."""
    reference = random_game(game_seed, policy_seed)
    game = FishEnv()
    game.reset(seed=game_seed)
    feed(game, reference)
    assert game.actions == reference
    assert game.game.phase is Phase.OVER
    assert game.agents == list(AGENTS)  # finished, not yet stepped out


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_golden_games_are_environment_games(path: Path) -> None:
    """Every golden game, given to the environment one seat action at a time, applies the same
    actions and passes through the same states, checked by hash after every agent step."""
    golden: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    actions = tuple(action_from_data(data) for data in golden["actions"])
    game = FishEnv()
    game.reset(seed=int(golden["seed"]))
    for action in actions:
        if isinstance(action, OpenWindow | CloseWindow):
            continue
        game.step(encode(action))
        assert state_hash(game.game) == golden["hashes"][len(game.actions) - 1]
    assert game.actions == actions
    record = game.record()
    assert (record["outcome"], record["winner"]) == (golden["outcome"], golden["winner"])


# ---------------------------------------------------------------- R.9 under random agents


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64)
def test_r9_invariants_hold_at_every_agent_step(game_seed: int, policy_seed: int) -> None:
    """R.9 at every agent step of a game played by uniformly random legal agents: the state is
    consistent, the selected agent is the lowest seat that may act and has a legal action, the
    turn never falls to a player without cards, and the game ends."""
    game = FishEnv()
    game.reset(seed=game_seed)
    rng = np.random.default_rng(policy_seed)
    for agent in game.agent_iter():
        observation, reward, terminated, truncated, _ = game.last()
        if terminated or truncated:
            game.step(None)
            continue
        assert reward == 0
        assert observation is not None
        state = game.game
        check_consistency(state)
        assert seat_of(agent) == acting_seats(state)[0]
        assert game.observation_space(agent).contains(observation)
        legal = np.flatnonzero(observation["action_mask"])
        assert legal.size > 0, "R.9: the selected agent can always act"
        if state.phase in (Phase.TURN, Phase.RUNOUT):
            assert state.current is not None
            assert state.hands[state.current], "R.9: the turn fell to a player without cards"
        game.step(int(rng.choice(legal)))
    assert game.game.phase is Phase.OVER
    assert game.agents == []
