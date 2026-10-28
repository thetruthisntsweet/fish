"""The environment's memory wrapper (T2.8): PettingZoo's checks pass under every setting, the
observations are the plain environment's, and every agent's ``infos`` holds, at every step,
the observation it had just after each event it remembers: every event so far, the latest k,
or none."""

from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray
from pettingzoo.test import api_test, seed_test

from fish_env import AGENTS, FishEnv, env
from fish_env.memory import MemoryWrapper, memory_env
from fish_rules.observation import OBS_SIZE

U64 = st.integers(min_value=0, max_value=2**64 - 1)
GAMES: int = max(10, int(settings().max_examples) // 40)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Whole games, every agent's memory at every step: a fortieth of the profile's examples
(10 in dev, 25 in CI, 1,250 nightly)."""

ADVISORY = (  # as in test_conformance: advice that does not fit a masked card game
    "ignore:Observation space for each agent probably should be:UserWarning",
    "ignore:Observation is not a NumPy array:UserWarning",
)

type Memories = dict[str, NDArray[np.int8] | None]


@pytest.mark.filterwarnings(*ADVISORY)
@pytest.mark.parametrize("remembered", [None, 0, 1, 8])
def test_pettingzoo_api_and_seed_tests(remembered: int | None) -> None:
    api_test(memory_env(remembered), num_cycles=500)
    seed_test(lambda: memory_env(remembered), num_cycles=500)


def play(game: Any, game_seed: int, policy_seed: int) -> list[tuple[int, Memories, Any]]:
    """Play ``game`` with random legal actions. After reset and every step: the number of
    events so far, every live agent's memory (None in the plain environment), and the
    observation every agent is shown then."""
    rng = np.random.default_rng(policy_seed)
    game.reset(seed=game_seed)

    def now() -> tuple[int, Memories, Any]:
        memories = {agent: game.infos[agent].get("memory") for agent in game.agents}
        shown = {agent: game.observe(agent)["observation"] for agent in AGENTS}
        return game.unwrapped.game.events, memories, shown

    seen = [now()]
    for agent in game.agent_iter():
        observation, _, terminated, truncated, info = game.last()
        assert info is game.infos[agent]
        if terminated or truncated:
            game.step(None)
        else:
            game.step(int(rng.choice(np.flatnonzero(observation["action_mask"]))))
        seen.append(now())
    return seen


def check_game(remembered: int | None, game_seed: int, policy_seed: int) -> None:
    """The same random game in the wrapped and the plain environment. The observations match;
    and at every step, every live agent's memory is, for the latest events its setting keeps,
    the observation the plain environment showed it just after each one."""
    ours = play(memory_env(remembered), game_seed, policy_seed)
    plain = play(env(), game_seed, policy_seed)
    assert len(ours) == len(plain)
    shown_after: dict[str, list[NDArray[np.int8]]] = {agent: [] for agent in AGENTS}
    previous = 0
    for (events, memories, shown), (plain_events, _, plain_shown) in zip(ours, plain, strict=True):
        assert events == plain_events
        assert all(np.array_equal(shown[a], plain_shown[a]) for a in AGENTS)
        if events > previous:  # one action makes at most one event
            assert events == previous + 1
            for agent in AGENTS:
                shown_after[agent].append(plain_shown[agent])
            previous = events
        for agent, memory in memories.items():
            rows = shown_after[agent]
            keep = rows if remembered is None else rows[-remembered:] if remembered else []
            assert memory is not None
            assert memory.dtype == np.int8
            assert memory.shape == (len(keep), OBS_SIZE)
            assert np.array_equal(memory, np.array(keep, np.int8).reshape(-1, OBS_SIZE)), agent


@pytest.mark.parametrize("remembered", [None, 0, 1, 3])
def test_every_agent_remembers_what_its_setting_keeps(remembered: int | None) -> None:
    check_game(remembered, 7, 8)


def test_the_end_of_the_game_keeps_its_result_and_the_memory() -> None:
    game = memory_env()
    game.reset(seed=2)
    rng = np.random.default_rng(3)
    while not any(game.terminations.values()) and not any(game.truncations.values()):
        observation = game.observe(game.agent_selection)
        assert observation is not None
        game.step(int(rng.choice(np.flatnonzero(observation["action_mask"]))))
    unwrapped = game.unwrapped
    assert isinstance(unwrapped, FishEnv)
    events = unwrapped.game.events
    for agent in game.agents:
        assert set(game.infos[agent]) == {"outcome", "winner", "memory"}
        assert game.infos[agent]["memory"].shape == (events, OBS_SIZE)
    game.reset(seed=2)  # a new game forgets
    assert all(game.infos[agent]["memory"].shape == (0, OBS_SIZE) for agent in game.agents)


def test_the_wrapper_needs_the_fish_environment_and_a_setting() -> None:
    for wrong in (-1, True, "3", 2.5):
        with pytest.raises(ValueError, match="number of events"):
            MemoryWrapper(env(), wrong)  # pyright: ignore[reportArgumentType]

    class Other:
        unwrapped = object()

    with pytest.raises(TypeError, match="wraps the Fish environment"):
        MemoryWrapper(Other())  # pyright: ignore[reportArgumentType]
    assert str(memory_env(4)) == "MemoryWrapper<fish_v0, remembered=4>"
    assert memory_env(4).memory("seat_0").shape == (0, OBS_SIZE)  # before reset


@settings(max_examples=GAMES, deadline=None)
@given(U64, U64, st.sampled_from([None, 0, 1, 2, 5, 20]))
def test_memories_over_random_games(
    game_seed: int, policy_seed: int, remembered: int | None
) -> None:
    check_game(remembered, game_seed, policy_seed % 2**32)
