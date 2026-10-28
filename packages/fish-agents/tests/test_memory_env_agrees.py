"""The environment's memory wrapper (``fish_env.memory``) and an agent's ``Memory``
(``fish_agents.memory``) remember the same thing: for every setting, at every step of a game,
an agent's remembered observations are its ``Memory``'s remembered views, encoded."""

import numpy as np
import pytest

from fish_agents.b0 import B0
from fish_agents.base import PolicyStreams
from fish_agents.memory import FULL, NONE, Memory, MemorySetting
from fish_env import AGENTS
from fish_env.env import FishEnv, seat_of
from fish_env.memory import memory_env
from fish_rules.observation import OBS_SIZE, encode


@pytest.mark.parametrize("setting", [FULL, NONE, MemorySetting.last_k(1), MemorySetting.last_k(6)])
@pytest.mark.parametrize("game_seed", [4, 9])
def test_the_wrapper_and_memory_agree(setting: MemorySetting, game_seed: int) -> None:
    game = memory_env(setting.remembered)
    game.reset(seed=game_seed)
    unwrapped = game.unwrapped
    assert isinstance(unwrapped, FishEnv)
    memories = {agent: Memory(seat_of(agent), setting) for agent in AGENTS}
    streams = PolicyStreams(game_seed)
    steps = 0
    while game.agents:
        for agent in game.agents:
            memories[agent].observe(unwrapped.view(agent))
            views = memories[agent].views
            rows = [np.frombuffer(encode(view), np.int8) for view in views]
            expected = np.array(rows, np.int8).reshape(-1, OBS_SIZE)
            assert np.array_equal(game.infos[agent]["memory"], expected), (agent, steps)
        agent = game.agent_selection
        if game.terminations[agent] or game.truncations[agent]:
            game.step(None)
            continue
        view = unwrapped.view(agent)
        game.step(B0().act(view, streams.for_decision(seat_of(agent), unwrapped.game.events)))
        steps += 1
    assert steps > 0
