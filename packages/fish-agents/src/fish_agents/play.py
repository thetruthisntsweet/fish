"""Play a whole environment game with six agents (T5.1).

``play_game(agents, game_seed)`` seats ``agents[s]`` at seat ``s`` of a ``fish_env.FishEnv``,
asks whichever agent the environment selects for an action until the game is over, and
returns the game record (``fish_rules.record``). Each agent sees only its own view and draws
its randomness from ``PolicyStreams``, so the same agents and game seed always give the same
game. An agent that returns an illegal action raises ``IllegalActionError``.

It needs the environment: install fish-agents with its ``env`` extra (the workspace's
``uv sync --all-packages`` already has it). The server never imports this module.
"""

from collections.abc import Sequence

from fish_agents.base import Agent, PolicyStreams
from fish_env.env import FishEnv, seat_of
from fish_rules.cards import NUM_SEATS


def play_game(agents: Sequence[Agent], game_seed: int) -> dict[str, object]:
    """Play one game from ``game_seed`` with ``agents[s]`` in seat ``s``; return its record."""
    if len(agents) != NUM_SEATS:
        raise ValueError(f"a game needs {NUM_SEATS} agents, got {len(agents)}")
    game = FishEnv()
    game.reset(seed=game_seed)
    streams = PolicyStreams(game_seed)
    while game.agents:
        agent = game.agent_selection
        if game.terminations[agent] or game.truncations[agent]:
            game.step(None)
            continue
        seat = seat_of(agent)
        rng = streams.for_decision(seat, game.game.events)
        game.step(agents[seat].act(game.view(agent), rng))
    return game.record()
