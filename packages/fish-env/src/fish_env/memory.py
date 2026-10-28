"""Agent memory in the environment, for training (T2.8).

``FishEnv`` gives each agent its seat's view now, with only the most recent event (R.2.2).
``MemoryWrapper`` adds what the agent remembers: for each remembered event, the observation
the agent had just after it, as ``fish-obs-v1`` bits. They are in the agent's ``infos`` entry
under ``"memory"``, an ``int8`` array of shape ``(events remembered, 648)``, oldest first, so
the observation and action spaces stay exactly ``FishEnv``'s and any policy written for it
still runs:

    game = memory_env(remembered=8)     # the last 8 events; None for all, 0 for none
    game.reset(seed=42)
    for agent in game.agent_iter():
        observation, reward, terminated, truncated, info = game.last()
        past = info["memory"]            # shape (n, 648), n <= 8

``remembered`` counts events, as ``fish_agents.memory.MemorySetting.remembered`` does (D57):
None keeps every event, k keeps the latest k, 0 keeps none. Every agent is shown every
event, whoever acts, because the wrapper looks at every seat's view after every step, as a
player at the table would see it.
"""

from typing import Any

import numpy as np
from numpy.typing import NDArray
from pettingzoo import AECEnv
from pettingzoo.utils import BaseWrapper

from fish_env.env import ActionIndex, FishEnv, Observation, env
from fish_rules.observation import OBS_SIZE


class MemoryWrapper(BaseWrapper[str, Observation, ActionIndex]):
    """``game`` (a ``FishEnv``, wrapped or not) with each agent's remembered observations in
    its ``infos`` entry under ``"memory"``."""

    def __init__(self, game: AECEnv[str, Observation, ActionIndex], remembered: int | None = None):
        if remembered is not None and (
            not isinstance(remembered, int) or isinstance(remembered, bool) or remembered < 0
        ):
            raise ValueError(
                f"remembered is None or a number of events, 0 or more, not {remembered!r}"
            )
        if not isinstance(game.unwrapped, FishEnv):
            raise TypeError("MemoryWrapper wraps the Fish environment")
        super().__init__(game)
        self.remembered = remembered
        self._kept: dict[str, list[tuple[int, NDArray[np.int8]]]] = {}

    def reset(self, seed: int | None = None, options: dict[str, Any] | None = None) -> None:
        super().reset(seed=seed, options=options)
        self._kept = {agent: [] for agent in self.possible_agents}
        self._remember()

    def step(self, action: ActionIndex) -> None:
        super().step(action)
        self._remember()

    def memory(self, agent: str) -> NDArray[np.int8]:
        """``agent``'s remembered observations, oldest first: shape ``(n, 648)``."""
        kept = self._kept.get(agent, [])
        if not kept:
            return np.zeros((0, OBS_SIZE), np.int8)
        return np.stack([observation for _, observation in kept])

    def _remember(self) -> None:
        """Show every seat its view: keep the observation of each new event, then put each
        live agent's memory in its ``infos`` entry."""
        game = self.unwrapped
        assert isinstance(game, FishEnv)
        for agent in self.possible_agents:
            event = game.view(agent).last_event
            kept = self._kept[agent]
            if event is not None and (not kept or kept[-1][0] != event.number):
                kept.append((event.number, game.observe(agent)["observation"]))
            if self.remembered is not None:
                del kept[: max(0, len(kept) - self.remembered)]
            if agent in game.infos:
                game.infos[agent]["memory"] = self.memory(agent)

    def __str__(self) -> str:
        return f"{type(self).__name__}<{self.env}, remembered={self.remembered}>"


def memory_env(remembered: int | None = None) -> MemoryWrapper:
    """``fish_env.env()`` with memory: every event kept (None), the latest ``remembered``, or
    none (0)."""
    return MemoryWrapper(env(), remembered)
