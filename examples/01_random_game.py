"""Play one game of Fish in the PettingZoo environment with random legal moves.

Every agent picks uniformly among the actions its mask allows. The game is fixed by its seed:
playing again from the same seed with the same choices gives the same game, which the record
shows. Run: python 01_random_game.py
"""

import numpy as np

from fish_env import FishEnv


def play(seed: int) -> dict[str, object]:
    """One game from ``seed``; every choice is drawn from a generator seeded by ``seed``."""
    game = FishEnv()  # fish_env.env() is the same game with PettingZoo's extra checks
    game.reset(seed=seed)
    rng = np.random.default_rng(seed)
    final: dict[str, float] = {}
    for agent in game.agent_iter():
        observation, reward, terminated, truncated, _ = game.last()
        if terminated or truncated:
            final[agent] = reward
            game.step(None)
            continue
        assert observation is not None  # every agent still playing has one
        legal = np.flatnonzero(observation["action_mask"])
        game.step(int(rng.choice(legal)))
    record = game.record()
    print(
        f"seed {seed}: {len(game.actions)} actions, outcome {record['outcome']}, "
        f"winner team {record['winner']}"
    )
    print("  rewards:", {agent: int(r) for agent, r in sorted(final.items())})
    return record


first = play(7)
again = play(7)
assert first == again, "the same seed and the same choices give the same game"
print("same seed, same game: yes")
